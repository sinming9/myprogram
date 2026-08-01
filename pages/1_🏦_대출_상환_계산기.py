import json
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import 날짜로, 숫자로, 최대_연도, 최소_연도  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines.loan import 스케줄_생성, 요약, 이자정산방식_목록  # noqa: E402

require_login(page_title="대출 상환 계산기", page_icon="🏦", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("🏦 대출 상환 계산기")
st.caption("고정→변동금리 · 날짜 기준 중도상환 · 중도상환수수료 반영 · 휴대폰에서도 그대로 씁니다")

# ==========================================================================
# 기본값 & 상태 초기화
# ==========================================================================
기본_금리 = [{"시작회차": 61, "금리(%)": 4.2}]
기본_중도 = [{"날짜": "2028-03-15", "금액": 50_000_000, "방식": "기간단축형",
             "이자(직접입력)": None, "수수료(직접입력)": None}]

기본값 = {
    "원금_입력": 500_000_000,
    "대출시작일_입력": date(2026, 8, 10),
    "첫납입일_입력": date(2026, 9, 25),
    "상환개월수_입력": 360,
    "연이율_입력": 3.5,
    "상환방식_입력": "원리금균등",
    "영업일_입력": True,
    "정산방식_입력": "원금분만",
    "수수료율_입력": 1.2,
    "면제기간_입력": 36,
}


def _상태초기화():
    for 키, 값 in 기본값.items():
        st.session_state.setdefault(키, 값)
    st.session_state.setdefault("금리_원본", [dict(r) for r in 기본_금리])
    st.session_state.setdefault("중도_원본", [dict(r) for r in 기본_중도])
    st.session_state.setdefault("표_버전", 0)


_상태초기화()


def _설정_딕셔너리(금리df, 중도df):
    return {
        "원금": int(st.session_state["원금_입력"]),
        "대출시작일": st.session_state["대출시작일_입력"].isoformat(),
        "첫납입일": st.session_state["첫납입일_입력"].isoformat(),
        "상환개월수": int(st.session_state["상환개월수_입력"]),
        "연이율": float(st.session_state["연이율_입력"]),
        "상환방식": st.session_state["상환방식_입력"],
        "영업일_적용": bool(st.session_state["영업일_입력"]),
        "이자정산방식": st.session_state["정산방식_입력"],
        "수수료율": float(st.session_state["수수료율_입력"]),
        "면제기간_개월": int(st.session_state["면제기간_입력"]),
        "금리스케줄": _금리_직렬화(금리df),
        "중도상환목록": _중도_직렬화(중도df),
    }


def _금리_직렬화(df):
    출력 = []
    for _, row in df.iterrows():
        if pd.isna(row.get("시작회차")) or pd.isna(row.get("금리(%)")):
            continue
        출력.append({"시작회차": int(row["시작회차"]), "금리(%)": float(row["금리(%)"])})
    return 출력


def _중도_읽기(df):
    """중도상환 표를 읽어서 (정상목록, 문제메시지목록) 을 돌려줍니다.

    ※ 예전에는 날짜를 못 읽으면 그 줄을 조용히 건너뛰어서, 연도를 잘못 넣으면
      계산에서 사라진 걸 알 수가 없었습니다. 이제는 이유를 화면에 알려줍니다.
    """
    출력, 문제 = [], []
    for 순번, (_, row) in enumerate(df.iterrows(), start=1):
        날짜값 = row.get("날짜")
        금액값 = row.get("금액")
        비어있음 = (날짜로(날짜값) is None and 숫자로(금액값, 0) <= 0)
        if 비어있음:
            continue                      # 완전히 빈 줄은 조용히 무시

        d = 날짜로(날짜값)
        if d is None:
            문제.append(f"{순번}번째 줄: 날짜를 읽을 수 없습니다 "
                      f"(입력값 {날짜값!r}). {최소_연도}~{최대_연도}년 범위의 "
                      f"연-월-일을 모두 넣어주세요.")
            continue
        금액 = 숫자로(금액값, 0)
        if 금액 <= 0:
            문제.append(f"{순번}번째 줄({d}): 금액이 비어 있거나 0 입니다.")
            continue
        시작일 = st.session_state.get("대출시작일_입력")
        if 시작일 and d < 시작일:
            문제.append(f"{순번}번째 줄({d}): 대출시작일({시작일}) 보다 앞선 날짜입니다.")
            continue

        이자 = row.get("이자(직접입력)")
        수수료 = row.get("수수료(직접입력)")
        출력.append({
            "날짜": d.isoformat(),
            "금액": int(round(금액)),
            "방식": row.get("방식") or "기간단축형",
            "이자(직접입력)": None if pd.isna(이자) else int(round(숫자로(이자))),
            "수수료(직접입력)": None if pd.isna(수수료) else int(round(숫자로(수수료))),
        })
    return 출력, 문제


def _중도_직렬화(df):
    return _중도_읽기(df)[0]


def _설정_적용(data):
    """저장된 설정을 상태에 반영. 표 위젯은 버전을 올려서 깨끗하게 다시 그립니다."""
    st.session_state["원금_입력"] = int(data.get("원금", 기본값["원금_입력"]))
    st.session_state["대출시작일_입력"] = date.fromisoformat(
        str(data.get("대출시작일", 기본값["대출시작일_입력"].isoformat()))[:10])
    st.session_state["첫납입일_입력"] = date.fromisoformat(
        str(data.get("첫납입일", 기본값["첫납입일_입력"].isoformat()))[:10])
    st.session_state["상환개월수_입력"] = int(data.get("상환개월수", 360))
    st.session_state["연이율_입력"] = float(data.get("연이율", 3.5))
    방식 = data.get("상환방식", "원리금균등")
    st.session_state["상환방식_입력"] = 방식 if 방식 in ("원리금균등", "원금균등") else "원리금균등"
    st.session_state["영업일_입력"] = bool(data.get("영업일_적용", True))
    정산 = data.get("이자정산방식", "원금분만")
    st.session_state["정산방식_입력"] = 정산 if 정산 in 이자정산방식_목록 else "원금분만"
    st.session_state["수수료율_입력"] = float(data.get("수수료율", 1.2))
    st.session_state["면제기간_입력"] = int(data.get("면제기간_개월", 36))

    금리목록 = data.get("금리스케줄") or []
    st.session_state["금리_원본"] = [dict(r) for r in 금리목록] if 금리목록 else [dict(r) for r in 기본_금리]

    중도목록 = []
    for r in (data.get("중도상환목록") or []):
        항목 = dict(r)
        # 옛 버전 키 이름도 받아줍니다.
        if "이자(직접입력, 선택)" in 항목:
            항목["이자(직접입력)"] = 항목.pop("이자(직접입력, 선택)")
        항목.setdefault("이자(직접입력)", None)
        항목.setdefault("수수료(직접입력)", None)
        중도목록.append(항목)
    st.session_state["중도_원본"] = 중도목록 if 중도목록 else [dict(r) for r in 기본_중도]

    # ★ 표 위젯 초기화 (이걸 안 하면 이전 편집 내용이 새 자료 위에 다시 덮여
    #    행이 중복되거나 사라지는 현상이 생깁니다)
    st.session_state["표_버전"] += 1


# 이 브라우저 세션에서 처음 열었으면 저장된 설정을 자동으로 불러오기
if not st.session_state.get("_대출_자동로드", False):
    st.session_state["_대출_자동로드"] = True
    저장된 = storage.불러오기("loan", None)
    if 저장된:
        try:
            _설정_적용(저장된)
        except Exception:  # noqa: BLE001
            pass

st.sidebar.page_link("pages/8_📥_자료_가져오기.py", label="예전 자료 올리기", icon="📥")
storage.임시서버_안내()

# ==========================================================================
# 1. 기본 입력값
# ==========================================================================
st.subheader("1. 기본 입력값")

c1, c2 = st.columns(2)
c1.number_input("대출원금(원)", min_value=0, step=1_000_000, key="원금_입력")
c2.number_input("상환개월수", min_value=1, step=1, key="상환개월수_입력")

c3, c4 = st.columns(2)
c3.date_input("대출시작일", key="대출시작일_입력")
c4.date_input("첫납입일", key="첫납입일_입력")

c5, c6 = st.columns(2)
c5.number_input("최초 연이율(%)", min_value=0.0, step=0.05, format="%.2f", key="연이율_입력")
c6.selectbox("상환방식", ["원리금균등", "원금균등"], key="상환방식_입력")

st.checkbox("정기납입일이 주말·공휴일이면 다음 영업일로 이동", key="영업일_입력")
st.caption("공휴일 목록은 2025~2026년까지 반영되어 있습니다. 그 이후는 주말과 고정 공휴일만 적용됩니다.")

# ==========================================================================
# 2. 금리 스케줄
# ==========================================================================
st.subheader("2. 금리 스케줄")
st.caption("몇 회차부터 금리가 바뀌는지 추가하세요. 1회차를 따로 넣지 않으면 위의 최초 연이율이 자동 적용됩니다.")

금리_기준df = pd.DataFrame(st.session_state["금리_원본"] or 기본_금리)
금리df = st.data_editor(
    금리_기준df,
    num_rows="dynamic",
    width="stretch",
    key=f"금리_editor_{st.session_state.get('표_버전', 0)}",
    column_config={
        "시작회차": st.column_config.NumberColumn(min_value=1, step=1),
        "금리(%)": st.column_config.NumberColumn(min_value=0.0, step=0.05, format="%.2f"),
    },
)

# ==========================================================================
# 3. 중도상환 목록
# ==========================================================================
st.subheader("3. 중도상환 목록")

중도_기준df = pd.DataFrame(st.session_state["중도_원본"] or 기본_중도)
for 열, 기본 in (("날짜", None), ("금액", 0), ("방식", "기간단축형"),
              ("이자(직접입력)", None), ("수수료(직접입력)", None)):
    if 열 not in 중도_기준df.columns:
        중도_기준df[열] = 기본
중도_기준df = 중도_기준df[["날짜", "금액", "방식", "이자(직접입력)", "수수료(직접입력)"]]

# ★ 날짜 열은 반드시 object dtype + datetime.date 로 둡니다.
#   pd.to_datetime 으로 datetime64 로 만들면 pandas 3.x 에서
#   "Invalid value ... for dtype 'datetime64[us]'" TypeError 가 나면서
#   달력에서 고른 날짜(연도 포함)가 표에 반영되지 않습니다.
#   (DateColumn 은 datetime.date 를 돌려주는데 datetime64 열이 이를 거부함)
중도_기준df["날짜"] = pd.Series([날짜로(v) for v in 중도_기준df["날짜"]], dtype="object")
for _열 in ("금액", "이자(직접입력)", "수수료(직접입력)"):
    중도_기준df[_열] = pd.to_numeric(중도_기준df[_열], errors="coerce")

중도df = st.data_editor(
    중도_기준df,
    num_rows="dynamic",
    width="stretch",
    key=f"중도_editor_{st.session_state.get('표_버전', 0)}",
    column_config={
        "날짜": st.column_config.DateColumn(
            format="YYYY-MM-DD",
            min_value=date(최소_연도, 1, 1),
            max_value=date(최대_연도, 12, 31),
            help="달력에서 고르거나 2028-03-15 형태로 입력하세요"),
        "금액": st.column_config.NumberColumn(min_value=0, step=1_000_000, format="%d"),
        "방식": st.column_config.SelectboxColumn(options=["기간단축형", "상환액감소형"]),
        "이자(직접입력)": st.column_config.NumberColumn(
            min_value=0, step=1000, format="%d",
            help="비워두면 자동 계산. 은행 명세서 값을 알면 그 값을 넣으세요."),
        "수수료(직접입력)": st.column_config.NumberColumn(
            min_value=0, step=1000, format="%d",
            help="비워두면 아래 수수료율로 자동 계산"),
    },
)
st.caption(
    "실제 상환한(할) 날짜를 그대로 입력하세요. 날짜는 **연·월·일을 모두** 채워야 합니다. "
    "**기간단축형**은 월 납입액을 유지하고 기간을 줄이며, **상환액감소형**은 기간을 유지하고 월 납입액을 줄입니다."
)

# 입력한 줄 중에 문제가 있으면 계산 전에 바로 알려줍니다.
_읽은목록, _문제목록 = _중도_읽기(중도df)
for _메시지 in _문제목록:
    st.warning(_메시지, icon="⚠️")
if _읽은목록:
    st.caption("반영될 중도상환: " + ", ".join(
        f"{r['날짜']} {r['금액']:,}원({r['방식'][:4]})" for r in _읽은목록))

with st.expander("⚙️ 중도상환 계산 옵션 (이자 정산방식 · 수수료)"):
    st.radio(
        "경과이자 정산방식",
        이자정산방식_목록,
        key="정산방식_입력",
        help="은행 명세서와 총이자를 맞출 때 조정하세요.",
    )
    st.caption(
        "· **원금분만** (기본, 국내 은행 일반 관행) — 중도상환일에는 *상환하는 원금*에 대한 "
        "경과이자만 정산하고, 남은 잔액의 이자는 다음 정기납입일에 한 달치로 냅니다.\n\n"
        "· **전체잔액 일수정산** — 중도상환일에 전체 잔액의 경과이자를 정산하고, "
        "다음 정기납입일에는 남은 일수만큼만 이자를 냅니다.\n\n"
        "두 방식 모두 같은 기간의 이자를 두 번 계산하지 않습니다."
    )
    f1, f2 = st.columns(2)
    f1.number_input("중도상환수수료율(%)", min_value=0.0, max_value=5.0, step=0.1,
                    format="%.2f", key="수수료율_입력",
                    help="0 으로 두면 수수료를 계산하지 않습니다. 보통 1.2~1.4%")
    f2.number_input("수수료 면제기간(개월)", min_value=0, max_value=120, step=6,
                    key="면제기간_입력", help="보통 36개월. 이 기간이 지나면 수수료 0원")
    st.caption("수수료 = 중도상환원금 × 수수료율 × 잔여면제기간일수 ÷ 전체면제기간일수 (슬라이딩 방식)")

# ==========================================================================
# 저장 / 계산
# ==========================================================================
b1, b2 = st.columns(2)
계산클릭 = b1.button("📊 계산하기", type="primary", width="stretch")

if b2.button("💾 이 설정을 기본값으로 저장", width="stretch"):
    성공, 메시지 = storage.저장하기("loan", _설정_딕셔너리(금리df, 중도df))
    (st.success if 성공 else st.error)(메시지)

with st.expander("⬇️⬆️ 설정 파일로 내보내기 / 불러오기 (다른 기기로 옮길 때)"):
    st.download_button(
        "현재 설정 JSON 내려받기",
        data=json.dumps(_설정_딕셔너리(금리df, 중도df), ensure_ascii=False, indent=2),
        file_name="대출계산기_설정.json",
        mime="application/json",
        width="stretch",
    )
    업로드 = st.file_uploader("설정 JSON 올리기", type=["json"], key="loan_upload")
    if 업로드 is not None and st.button("올린 설정 적용", width="stretch"):
        try:
            _설정_적용(json.load(업로드))
            st.success("불러왔습니다.")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"불러오기 실패: {e}")

# ==========================================================================
# 결과
# ==========================================================================
if not 계산클릭:
    st.caption("입력값을 확인한 뒤 '계산하기' 버튼을 눌러주세요.")
    st.stop()

try:
    원금 = int(st.session_state["원금_입력"])
    대출시작일 = st.session_state["대출시작일_입력"]
    첫납입일 = st.session_state["첫납입일_입력"]
    상환개월수 = int(st.session_state["상환개월수_입력"])
    연이율 = float(st.session_state["연이율_입력"])
    상환방식 = st.session_state["상환방식_입력"]
    영업일_적용 = bool(st.session_state["영업일_입력"])
    정산방식 = st.session_state["정산방식_입력"]
    수수료율 = float(st.session_state["수수료율_입력"])
    면제기간 = int(st.session_state["면제기간_입력"])

    금리스케줄 = [{"start_month": r["시작회차"], "rate": r["금리(%)"]}
               for r in _금리_직렬화(금리df)]
    if not any(r["start_month"] == 1 for r in 금리스케줄):
        금리스케줄.append({"start_month": 1, "rate": 연이율})

    중도상환목록 = [{
        "date": date.fromisoformat(r["날짜"]),
        "amount": r["금액"],
        "method": r["방식"],
        "interest": r["이자(직접입력)"],
        "fee": r["수수료(직접입력)"],
    } for r in _읽은목록]

    결과, 경고 = 스케줄_생성(원금, 대출시작일, 첫납입일, 상환개월수, 금리스케줄,
                         중도상환목록, 상환방식, 영업일_적용,
                         정산방식, 수수료율, 면제기간)
except Exception as e:  # noqa: BLE001
    st.error(f"계산 중 오류가 발생했습니다: {e}")
    st.stop()

for w in 경고:
    st.warning(w, icon="⚠️")

s = 요약(결과)

st.subheader("계산 결과")
ui.카드_줄([
    ("대출원금", f"{원금:,}원", f"{원금/1e8:.2f}억"),
    ("실제 상환개월수", f"{s['상환개월수']}개월", f"약 {s['상환개월수']/12:.1f}년 · 완납 {s['완납일']}"),
    ("총 이자", f"{s['총이자']:,}원", f"원금의 {s['총이자']/원금*100:.1f}%" if 원금 else ""),
    ("총 납입액", f"{s['총납입액']:,}원",
     f"중도상환수수료 {s['총수수료']:,}원 포함" if s["총수수료"] else "수수료 없음"),
], 열수=2)

if 중도상환목록:
    없는결과, _ = 스케줄_생성(원금, 대출시작일, 첫납입일, 상환개월수, 금리스케줄,
                          [], 상환방식, 영업일_적용, 정산방식, 수수료율, 면제기간)
    기준 = 요약(없는결과)
    이자절감 = 기준["총이자"] - s["총이자"]
    순절감 = 이자절감 - s["총수수료"]
    문구 = f"중도상환 효과: 이자 절감 **{이자절감:,}원**"
    if s["총수수료"]:
        문구 += f" − 수수료 **{s['총수수료']:,}원** = 순 효과 **{순절감:,}원**"
    if s["상환개월수"] < 기준["상환개월수"]:
        문구 += (f" · 상환기간 **{기준['상환개월수'] - s['상환개월수']}개월** 단축"
               f" ({기준['상환개월수']}개월 → {s['상환개월수']}개월)")
    st.success(문구, icon="💰")

표df = pd.DataFrame([{
    "구분": r["구분"],
    "회차": str(r["회차"]),
    "날짜": r["날짜"].strftime("%Y-%m-%d"),
    "금리(%)": r["적용금리"],
    "이자": r["이자"],
    "원금": r["원금"],
    "중도상환액": r["중도상환액"],
    "수수료": r.get("수수료", 0),
    "납입액": r["납입액"],
    "잔액": r["잔액"],
} for r in 결과])

보기 = st.radio("표 보기", ["전체", "중도상환·초기이자만", "연도별 요약"],
              horizontal=True, label_visibility="collapsed")

if 보기 == "중도상환·초기이자만":
    보여줄 = 표df[표df["구분"] != "정기납입"]
elif 보기 == "연도별 요약":
    임시 = 표df.copy()
    임시["연도"] = 임시["날짜"].str[:4]
    보여줄 = (임시.groupby("연도")[["이자", "원금", "중도상환액", "수수료", "납입액"]]
            .sum().reset_index())
    보여줄["연말 잔액"] = (임시.groupby("연도")["잔액"].last().values)
else:
    보여줄 = 표df


def _강조(row):
    if row.get("구분") in ("초기이자", "중도상환"):
        return ["background-color: rgba(255, 196, 0, .18)"] * len(row)
    return [""] * len(row)


숫자열 = [c for c in ("이자", "원금", "중도상환액", "수수료", "납입액", "잔액", "연말 잔액")
       if c in 보여줄.columns]
st.dataframe(
    보여줄.style.apply(_강조, axis=1).format({c: "{:,}" for c in 숫자열}),
    width="stretch", height=430, hide_index=True,
)

st.download_button(
    "📄 전체 상환표 CSV 내려받기",
    data=표df.to_csv(index=False).encode("utf-8-sig"),
    file_name="대출상환표.csv", mime="text/csv", width="stretch",
)

with st.expander("📌 계산 방식 설명"):
    st.markdown(
        f"""
- **정기납입 이자** — {'직전 정산일부터 실제 경과일수 기준' if 정산방식 == '전체잔액 일수정산' else '잔액 × 연이율 ÷ 12 (한 달치)'}
- **중도상환 경과이자** — {'전체 잔액 × 연이율 × 경과일 ÷ 365' if 정산방식 == '전체잔액 일수정산' else '중도상환 원금 × 연이율 × 경과일 ÷ 365'}
- **초기이자** — 대출시작일부터 첫납입일까지의 일수 이자 (그 사이 중도상환이 있으면 구간별 잔액으로 계산)
- **중도상환수수료** — 중도상환원금 × {수수료율:.2f}% × 잔여면제기간일수 ÷ 전체면제기간일수 (면제기간 {면제기간}개월)
- 실제 은행 고지액과 원 단위 차이는 반올림·이자계산일수(365/366) 관행 차이로 생길 수 있습니다.
  명세서 값을 알고 있으면 표의 **이자(직접입력)** / **수수료(직접입력)** 칸에 넣어 정확히 맞출 수 있습니다.
"""
    )
