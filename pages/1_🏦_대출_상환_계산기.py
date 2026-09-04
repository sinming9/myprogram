import json
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import (날짜로, 불러온것_적용, 숫자로,  # noqa: E402
                     저장_불러오기, 최대_연도, 최소_연도)
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines.loan import (스케줄_생성, 실적_대조, 요약,  # noqa: E402
                          이자정산방식_목록, 진행_현황)

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
    # 통장에서 확인한 실제 잔액. 계산값과 대조해 보려고 받습니다.
    #  ※ 계산에는 쓰지 않습니다. 차이를 '보정' 하는 게 아니라 '보여주는' 값입니다.
    "확인일_입력": None,
    "실제잔액_입력": 0,
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
        "확인일": (st.session_state["확인일_입력"].isoformat()
                if st.session_state.get("확인일_입력") else None),
        "실제잔액": int(st.session_state.get("실제잔액_입력") or 0),
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
    _확인일 = data.get("확인일")
    st.session_state["확인일_입력"] = (date.fromisoformat(str(_확인일)[:10])
                                  if _확인일 else None)
    st.session_state["실제잔액_입력"] = int(data.get("실제잔액") or 0)

    # ※ 빈 목록([])과 '항목 없음'(키 자체가 없음)을 구분합니다.
    #   예전에는 둘 다 기본값으로 되돌려서, 금리 스케줄을 지우고 저장해도
    #   다음에 열면 "61회차 4.2%" 가 계속 되살아났습니다.
    금리목록 = data.get("금리스케줄")
    st.session_state["금리_원본"] = ([dict(r) for r in 금리목록] if 금리목록 is not None
                                 else [dict(r) for r in 기본_금리])

    원본중도 = data.get("중도상환목록")
    중도목록 = []
    for r in (원본중도 or []):
        항목 = dict(r)
        # 옛 버전 키 이름도 받아줍니다.
        if "이자(직접입력, 선택)" in 항목:
            항목["이자(직접입력)"] = 항목.pop("이자(직접입력, 선택)")
        항목.setdefault("이자(직접입력)", None)
        항목.setdefault("수수료(직접입력)", None)
        중도목록.append(항목)
    st.session_state["중도_원본"] = (중도목록 if 원본중도 is not None
                                 else [dict(r) for r in 기본_중도])

    # ★ 표 위젯 초기화 (이걸 안 하면 이전 편집 내용이 새 자료 위에 다시 덮여
    #    행이 중복되거나 사라지는 현상이 생깁니다)
    st.session_state["표_버전"] += 1


# 올린 설정 파일 적용 — 반드시 입력칸(위젯)을 만들기 "전"에 처리해야 합니다.
불러온것_적용("_대출_적용대기", _설정_적용)

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
with st.expander("⚙️ 2. 금리 스케줄 — 변동금리면 여기에", expanded=bool(st.session_state.get('금리_원본'))):
    st.caption("몇 회차부터 금리가 바뀌는지 추가하세요. 1회차를 따로 넣지 않으면 위의 최초 연이율이 자동 적용됩니다.")
    if not st.session_state["금리_원본"]:
        st.caption("현재 등록된 금리 변동이 없습니다. 최초 연이율이 끝까지 적용됩니다.")

    # 비어 있으면 빈 표를 그대로 보여줍니다 (기본값을 다시 넣지 않습니다).
    금리_기준df = pd.DataFrame(st.session_state["금리_원본"], columns=["시작회차", "금리(%)"])
    for _열 in ("시작회차", "금리(%)"):
        금리_기준df[_열] = pd.to_numeric(금리_기준df[_열], errors="coerce")
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

with st.expander("💸 3. 중도상환 목록", expanded=bool(st.session_state.get('중도_원본'))):

    중도_기준df = pd.DataFrame(st.session_state["중도_원본"],
                            columns=["날짜", "금액", "방식", "이자(직접입력)", "수수료(직접입력)"])
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

계산클릭 = st.button("📊 계산하기", type="primary", width="stretch")

# ==========================================================================
# 결과
# ==========================================================================
if not 계산클릭:
    st.caption("입력값을 확인한 뒤 '계산하기' 버튼을 눌러주세요.")
    저장_불러오기("loan", _설정_딕셔너리(금리df, 중도df), "대출계산기_설정",
              "_대출_적용대기",
              도움말="다른 기기로 옮기거나 여러 조건을 따로 보관할 때 쓰세요.")
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

탭요약, 탭상환표 = st.tabs(["요약", "상환표"])

with 탭요약:
    # ======================================================================
    # 지금 어디까지 왔나
    # ======================================================================
    #  아래 '생애 전체' 숫자만 있으면 "총이자 3.6억" 같은 값은 나오지만,
    #  그중 얼마를 이미 냈고 얼마가 남았는지는 알 수 없습니다.
    진행 = 진행_현황(결과)

    ui.섹션("지금 어디까지 왔나",
          f"{진행['오늘']:%Y년 %m월 %d일} 기준입니다. 오늘까지 날짜가 지난 "
          "회차를 '낸 것' 으로 셉니다.", 라벨="현재")

    if not 진행["시작함"]:
        st.info(f"아직 첫 납입일({진행['다음납입일']}) 전입니다. "
                "납입이 시작되면 여기에 진행 상황이 나옵니다.", icon="📅")
    else:
        ui.카드_줄([
            ("낸 회차", f"{진행['낸회차']} / {진행['전체회차']}회",
             f"남은 {진행['남은회차']}회 · 완납 {진행['완납일']}", "파랑"),
            ("현재 잔액", ui.억(진행["현재잔액"]),
             f"원금 {진행['원금진행률']:.1f}% 상환", "빨강"),
            ("지금까지 낸 돈", ui.억(진행["낸총액"]),
             f"이자 {진행['낸이자'] / 1e4:,.0f}만 + 원금 "
             f"{진행['낸원금'] / 1e4:,.0f}만", "회색"),
            ("앞으로 낼 돈", ui.억(진행["남은총액"]),
             f"이자 {진행['남은이자'] / 1e4:,.0f}만 + 원금 "
             f"{진행['남은원금'] / 1e4:,.0f}만", "초록"),
        ], 열수=2)

        st.progress(min(진행["진행률"] / 100, 1.0),
                    text=f"회차 {진행['낸회차']}/{진행['전체회차']} "
                         f"({진행['진행률']:.0f}%)")
        st.progress(min(진행["원금진행률"] / 100, 1.0),
                    text=f"원금 상환 {진행['원금진행률']:.1f}% "
                         f"(회차는 {진행['진행률']:.0f}%)")
        if 진행["원금진행률"] < 진행["진행률"] - 3:
            st.caption("회차는 더 갔는데 원금은 덜 줄었습니다. 원리금균등은 "
                       "초반에 이자 비중이 커서 정상입니다.")

        if 진행["다음납입일"]:
            st.info(
                f"**다음 납입 {진행['다음납입일']:%Y-%m-%d}** — "
                f"{진행['다음납입액']:,.0f}원 "
                f"(이자 {진행['다음이자']:,.0f} + 원금 {진행['다음원금']:,.0f})\n\n"
                f"앞으로 낼 {ui.억(진행['남은총액'])} 중 "
                f"**{진행['남은이자비중']:.0f}% 가 이자**입니다.", icon="📅")

        with st.expander("낸 것 / 남은 것 나눠 보기"):
            st.dataframe(pd.DataFrame([
                {"구분": "지금까지 낸 것", "이자": round(진행["낸이자"]),
                 "원금": round(진행["낸원금"]), "수수료": round(진행["낸수수료"]),
                 "합계": round(진행["낸총액"])},
                {"구분": "앞으로 낼 것", "이자": round(진행["남은이자"]),
                 "원금": round(진행["남은원금"]), "수수료": round(진행["남은수수료"]),
                 "합계": round(진행["남은총액"])},
                {"구분": "전체", "이자": round(s["총이자"]),
                 "원금": round(s["총원금"]), "수수료": round(s["총수수료"]),
                 "합계": round(s["총납입액"])},
            ]).style.format({"이자": "{:,}", "원금": "{:,}",
                            "수수료": "{:,}", "합계": "{:,}"}),
                         width="stretch", hide_index=True)
            st.caption("'앞으로 낼 원금' 은 현재 잔액과 같습니다. "
                       "원 단위 절사 때문에 몇 원 차이가 날 수 있습니다.")
            if abs(진행["검산차이"]) > 10_000:
                st.warning(f"남은 원금과 현재 잔액이 "
                           f"{진행['검산차이']:+,.0f}원 어긋납니다. "
                           "설정을 확인해 주세요.", icon="⚠️")

    # ======================================================================
    # 통장 잔액과 맞춰보기
    # ======================================================================
    with st.expander("🏦 통장 잔액과 맞춰보기", expanded=False):
        st.caption(
            "계산 결과가 은행 잔액과 딱 맞는 일은 드뭅니다. 실제 잔액을 넣으면 "
            "**차이와 그 원인 후보**를 알려드립니다. "
            "이 값은 계산에 쓰지 않습니다 — 차이를 덮지 않고 보여주기만 합니다.")

        d1, d2 = st.columns(2)
        확인일 = d1.date_input(
            "통장 확인일", key="확인일_입력",
            min_value=date(최소_연도, 1, 1), max_value=date(최대_연도, 12, 31),
            help="그 날짜의 잔액을 아래에 넣으세요.")
        실제잔액 = d2.number_input("그 날 실제 잔액(원)", min_value=0,
                              step=1_000_000, key="실제잔액_입력")

        if 확인일 and 실제잔액 > 0:
            대조 = 실적_대조(결과, 확인일, 실제잔액)
            ui.카드_줄([
                ("계산 잔액", f"{대조['계산잔액']:,.0f}원",
                 (f"{대조['기준줄날짜']} 납입 후" if 대조["기준줄날짜"]
                  else "첫 납입 전")),
                ("통장 잔액", f"{대조['실제잔액']:,.0f}원", f"{확인일} 확인"),
                ("차이", f"{대조['차이']:+,.0f}원", f"{대조['차이율']:+.3f}%",
                 "초록" if 대조["판정"] == "절사수준" else
                 ("주황" if 대조["판정"] == "작은차이" else "빨강")),
            ], 열수=3)

            알림 = {"절사수준": st.success, "작은차이": st.info}.get(
                대조["판정"], st.warning)
            알림(f"**{대조['판정']}** — {대조['설명']}",
              icon="✅" if 대조["판정"] == "절사수준" else "⚠️")

            if 대조["원인후보"]:
                st.markdown("**차이가 나는 이유로 볼 수 있는 것**")
                for c in 대조["원인후보"]:
                    st.markdown(f"- {c}")
                st.caption(
                    "차이가 **매달 커지는지**가 중요합니다. 크기가 그대로면 "
                    "절사 규칙 차이라 무시해도 됩니다. 계속 벌어지면 금리 "
                    "스케줄이나 일수 계산 방식이 실제와 다른 것이니, 위 설정을 "
                    "실제 대출 약정서와 맞춰 주세요.")
        else:
            st.caption("확인일과 실제 잔액을 넣으면 대조 결과가 나옵니다.")

    st.divider()
    ui.섹션("대출 생애 전체", "처음부터 완납까지 합친 숫자입니다.", 라벨="전체")

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

with 탭상환표:
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


st.divider()
저장_불러오기("loan", _설정_딕셔너리(금리df, 중도df), "대출계산기_설정",
          "_대출_적용대기",
          도움말="다른 기기로 옮기거나 여러 조건을 따로 보관할 때 쓰세요.")
