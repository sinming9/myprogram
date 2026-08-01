import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importer  # noqa: E402
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402

require_login(page_title="자료 가져오기", page_icon="📥", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("📥 자료 가져오기")
st.caption("예전에 저장해 둔 파일을 올리면 형식을 알아보고 알맞은 프로그램으로 넣어줍니다.")

storage.임시서버_안내()

with st.expander("어떤 파일을 올릴 수 있나요?", expanded=False):
    st.markdown(
        "| 파일 | 어디서 만든 것 | 들어갈 곳 |\n"
        "|---|---|---|\n"
        "| `salary_data.json` | 예전 연봉 관리 프로그램 | 💰 연봉·급여 관리 |\n"
        "| `property_tax_settings.json` | 예전 재산세 계산기 (입력값) | 🏠 재산세·종부세 |\n"
        "| `property_tax_history.json` | 예전 재산세 계산기 (연도별 기록) | 🏠 재산세·종부세 |\n"
        "| `대출계산기_설정.json` | 대출 계산기 (구/신 버전) | 🏦 대출 상환 계산기 |\n"
        "| `연봉자료_백업_....json` 등 | 이 대시보드의 백업 | 원래 자리 |\n"
    )
    st.caption("여러 개를 한 번에 올려도 됩니다. 파일 이름은 달라도 내용으로 판별합니다.")

올린파일들 = st.file_uploader(
    "JSON 파일 올리기 (여러 개 선택 가능)", type=["json"],
    accept_multiple_files=True, key="가져오기_업로더",
)

if not 올린파일들:
    st.info("위에 파일을 올려주세요.", icon="⬆️")
    st.stop()

# ==========================================================================
# 판별 결과 보여주기
# ==========================================================================
결과들 = []
for f in 올린파일들:
    데이터, 종류, 오류 = importer.파일_읽기(f)
    결과들.append({"파일": f.name, "데이터": 데이터, "종류": 종류, "오류": 오류})

st.subheader("1. 읽은 파일")
표 = pd.DataFrame([{
    "파일": r["파일"],
    "알아본 형식": importer.종류_설명.get(r["종류"], ("?", None))[0],
    "내용": r["오류"] if r["오류"] else (
        importer.요약(r["종류"], r["데이터"]) if r["종류"] != "unknown" else "판별 실패"),
} for r in 결과들])
st.dataframe(표, width="stretch", hide_index=True)

쓸수있는것 = [r for r in 결과들 if not r["오류"] and r["종류"] != "unknown"]
못읽은것 = [r for r in 결과들 if r["오류"] or r["종류"] == "unknown"]

for r in 못읽은것:
    st.warning(f"`{r['파일']}` 은 가져올 수 없습니다. "
               f"{r['오류'] or '알 수 없는 형식입니다.'}", icon="⚠️")

if not 쓸수있는것:
    st.stop()

# ==========================================================================
# 옵션
# ==========================================================================
st.subheader("2. 가져오는 방법")
연봉있음 = any(r["종류"] == "salary" for r in 쓸수있는것)
합치기방식 = "덮어쓰기"
if 연봉있음:
    합치기방식 = st.radio(
        "연봉 자료에 이미 있는 연도를 만나면",
        ["덮어쓰기 (파일 내용으로 교체)", "건너뛰기 (기존 자료 유지)"],
        horizontal=False,
    )

st.caption("가져오기를 누르면 기존 자료를 바꾸므로, 먼저 각 페이지 사이드바의 "
           "**백업 / 복원**에서 현재 자료를 내려받아 두는 것을 권합니다.")

if not st.button("📥 가져오기 실행", type="primary", width="stretch"):
    st.stop()

# ==========================================================================
# 실제 가져오기
# ==========================================================================
st.subheader("3. 결과")
덮어쓰기 = 합치기방식.startswith("덮어쓰기")
재산세_모음 = None      # 설정/기록이 각각 다른 파일로 올 수 있어서 합쳐서 저장
바뀐것 = []

for r in 쓸수있는것:
    종류, 데이터, 이름 = r["종류"], r["데이터"], r["파일"]

    try:
        if 종류 == "salary":
            기존 = storage.불러오기("salary", {}) or {}
            합침, 추가, 덮음 = importer.연봉_합치기(기존, 데이터, 덮어쓰기)
            성공, 메시지 = storage.저장하기("salary", 합침)
            if 성공:
                st.session_state["급여_자료"] = 합침
                st.session_state["급여_표버전"] = st.session_state.get("급여_표버전", 0) + 1
                st.session_state.pop("급여_연도", None)
                말 = f"`{이름}` → 연봉·급여: 새로 추가 {len(추가)}개 연도"
                if 덮음:
                    말 += f", 덮어씀 {len(덮음)}개 연도"
                if 추가:
                    말 += f"  (추가: {', '.join(추가)})"
                st.success(말, icon="✅")
                바뀐것.append("salary")
            else:
                st.error(메시지)

        elif 종류 in ("property_tax_settings", "property_tax_history", "property_tax"):
            if 재산세_모음 is None:
                재산세_모음 = storage.불러오기("property_tax", {}) or {}
            if 종류 == "property_tax_settings":
                변환 = importer.재산세_설정_변환(데이터)
                기록보존 = 재산세_모음.get("history", [])
                재산세_모음.update(변환)
                재산세_모음["history"] = 기록보존 or 변환.get("history", [])
                st.success(f"`{이름}` → 재산세 입력값 {len(변환['부동산'])}건 가져옴", icon="✅")
            elif 종류 == "property_tax_history":
                재산세_모음["history"] = importer.재산세_기록_변환(데이터)
                st.success(f"`{이름}` → 재산세 연도별 기록 "
                           f"{len(재산세_모음['history'])}건 가져옴", icon="✅")
            else:
                재산세_모음.update(데이터)
                st.success(f"`{이름}` → 재산세 자료 전체 복원", icon="✅")
            바뀐것.append("property_tax")

        elif 종류 == "loan":
            변환 = importer.대출_설정_변환(데이터)
            성공, 메시지 = storage.저장하기("loan", 변환)
            if 성공:
                st.session_state.pop("_대출_자동로드", None)
                st.success(f"`{이름}` → 대출 계산기 설정 가져옴 "
                           f"(중도상환 {len(변환.get('중도상환목록', []))}건)", icon="✅")
                바뀐것.append("loan")
            else:
                st.error(메시지)

    except Exception as e:  # noqa: BLE001
        st.error(f"`{이름}` 가져오기 실패: {type(e).__name__}: {e}")

if 재산세_모음 is not None:
    성공, 메시지 = storage.저장하기("property_tax", 재산세_모음)
    if 성공:
        st.session_state["재산세_자료"] = 재산세_모음
        st.session_state["재산세_표버전"] = st.session_state.get("재산세_표버전", 0) + 1
    else:
        st.error(메시지)

if 바뀐것:
    st.divider()
    st.markdown("### 이제 확인해 보세요")
    if "salary" in 바뀐것:
        st.page_link("pages/4_💰_연봉_급여_관리.py", label="연봉·급여 관리 열기", icon="💰")
    if "property_tax" in 바뀐것:
        st.page_link("pages/3_🏠_재산세_종부세.py", label="재산세·종부세 열기", icon="🏠")
    if "loan" in 바뀐것:
        st.page_link("pages/1_🏦_대출_상환_계산기.py", label="대출 상환 계산기 열기", icon="🏦")
    st.caption("이미 열어둔 페이지가 있으면 한 번 다시 들어가야 새 자료가 보입니다.")
