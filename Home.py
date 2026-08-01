import streamlit as st

import addons
import storage
import ui
from auth import require_login, 로그아웃_버튼

require_login(page_title="개인 대시보드", page_icon="🗂️", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()
ui.사이드바_메뉴안내()

st.title("🗂️ 개인 대시보드")
st.caption("왼쪽 메뉴에서 원하는 프로그램을 선택하세요. 휴대폰에서는 화면 왼쪽 위 **»** 를 누르면 메뉴가 열립니다.")

storage.임시서버_안내()

프로그램 = [
    ("🏦", "대출 상환 계산기", "고정→변동금리, 날짜 기준 중도상환, 중도상환수수료까지 반영한 상환표",
     "pages/1_🏦_대출_상환_계산기.py"),
    ("💱", "환전 타이밍", "달러·엔·유로·위안·싱달러의 3년/1년/6개월/3개월/1개월 평균 대비 현재 환율",
     "pages/2_💱_환전_타이밍.py"),
    ("🏠", "재산세 · 종합부동산세", "보유 부동산별 공시가격·지분으로 7월/9월 재산세와 12월 종부세 계산",
     "pages/3_🏠_재산세_종부세.py"),
    ("💰", "연봉 · 급여 관리", "연도별 계약연봉·월별 급여 기록, 물가 대비 실질 인상률, 내년 권장 연봉",
     "pages/4_💰_연봉_급여_관리.py"),
    ("🥚", "금리 사이클", "코스톨라니 달걀 모형으로 보는 기준금리 위치와 국면별 자산 배분",
     "pages/5_🥚_금리_사이클.py"),
]

for 아이콘, 이름, 설명, 경로 in 프로그램:
    with st.container(border=True):
        st.markdown(f"### {아이콘} {이름}")
        st.caption(설명)
        st.page_link(경로, label=f"{이름} 열기", icon="➡️")

with st.container(border=True):
    st.markdown("### 📥 자료 가져오기")
    st.caption("예전 프로그램에서 저장해 둔 salary_data.json, property_tax_settings.json, "
               "대출계산기_설정.json 등을 올리면 알맞은 곳으로 넣어줍니다.")
    st.page_link("pages/8_📥_자료_가져오기.py", label="자료 가져오기 열기", icon="➡️")

# ---- myapps/ 폴더에 직접 넣은 프로그램들 ----
내프로그램 = addons.정상_목록()
with st.container(border=True):
    st.markdown("### ➕ 내 프로그램")
    if 내프로그램:
        st.caption("`myapps/` 폴더에서 찾은 프로그램 "
                   + " · ".join(f"{p['아이콘']} {p['제목']}" for p in 내프로그램))
    else:
        st.caption("`myapps/` 폴더에 .py 파일을 넣으면 여기에 자동으로 나타납니다.")
    st.page_link("pages/9_➕_내_프로그램.py", label="내 프로그램 열기", icon="➡️")

st.divider()
with st.expander("ℹ️ 사용 / 관리 안내"):
    st.markdown(
        "**저장 위치** — 입력한 자료는 앱 폴더의 `data/` 안에 JSON 파일로 저장됩니다. "
        "각 페이지 사이드바의 **백업 / 복원**으로 파일을 내려받거나 되돌릴 수 있습니다.\n\n"
        "**보안** — 비밀번호는 `.streamlit/secrets.toml` 에서 관리합니다. "
        "연속 실패 시 잠금, 12시간 후 자동 로그아웃이 적용됩니다.\n\n"
        "**외부 접속** — 같은 와이파이가 아닌 곳에서 접속하는 방법은 "
        "`외부접속_설정_가이드.md` 파일에 정리해 두었습니다.\n\n"
        "**화면 테마** — PC·휴대폰의 다크모드 설정을 자동으로 따라갑니다. "
        "직접 고르려면 우측 상단 **⋮ → Settings → Appearance**.\n\n"
        "**새 프로그램 추가** — 두 가지 방법이 있습니다.\n"
        "1. **간단한 방법** — `myapps/` 폴더에 `.py` 파일을 넣고 `실행()` 함수만 "
        "만들면 **➕ 내 프로그램** 메뉴에 자동으로 나타납니다. "
        "(예제: `myapps/예제_적금_계산기.py`)\n"
        "2. **독립 페이지** — `pages/` 폴더에 `5_🚗_이름.py` 형태로 넣으면 왼쪽 메뉴에 "
        "별도 항목으로 나타납니다. (템플릿: `pages/_템플릿.py.txt`)"
    )
