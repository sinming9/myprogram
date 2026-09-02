"""
==========================================================================
순자산 — 내 몫 / 가족 몫 / 가구 합계
==========================================================================
[이 페이지가 세 가지 값을 따로 보여주는 이유]

  가구 = 우리 집 전체 (전국 비교에 쓰는 값)
  개인 = 내 몫        (본인 명의 전액 + 공동명의 중 내 지분)
  가족 = 가구 − 개인  (배우자 명의 전액 + 공동명의 중 나머지)

가계금융복지조사는 **가구 단위** 통계라 전국 순위는 가구 기준으로 봐야
맞습니다. 그런데 "내가 실제로 가진 게 얼마냐" 는 가구 합계가 아닙니다.
두 값을 한 숫자로 뭉개면 어느 쪽도 알 수 없어서 나눠 두었습니다.

자산·부채는 **줄마다 소유자(본인/배우자/공동)** 를 붙여서 넣습니다.
공동명의는 등기 지분율을 적으면 그만큼만 내 몫으로 잡힙니다.
==========================================================================
"""

import os
import sys
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import 날짜로, 불러온것_적용, 숫자로, 저장_불러오기, 표만들기  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import networth as NW  # noqa: E402

require_login(page_title="순자산", page_icon="💎", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("💎 순자산")
st.caption(f"내 몫과 가족 몫을 나눠서 봅니다 · 비교 기준: "
           f"「{NW.조사연도}년 가계금융복지조사」 ({NW.조사기준일})")

저장키 = "networth"
기본설정 = {
    # 자산표 형식 표시. 2 = 소유자 태그가 붙은 표.
    #  ※ 이 표시가 없으면 예전 형식으로 보고 한 번 옮깁니다. 표시를 안 두면
    #    표를 전부 비우고 저장한 뒤 다시 열었을 때 예전 값이 되살아납니다.
    "형식": 2,
    "자산표": [],
    "기록": [],
    "기록기준": "가구",
    # ↓ 예전 버전(배우자 자산을 숫자 한 칸으로 받던 때)의 키.
    #   자산표로 한 번 옮긴 뒤에도 남겨 둡니다. 지우면 예전 백업 파일을
    #   다시 올렸을 때 옮길 재료가 없어집니다.
    "기타자산": {}, "기타부채": {}, "배우자자산": 0, "배우자부채": 0,
    "부동산시세": 0,
}


# ==========================================================================
# 다른 페이지에서 자동으로 끌어오기
# ==========================================================================
@st.cache_data(ttl=600, show_spinner=False)
def 자동_수집():
    """대출 잔액·부동산 공시가격·투자자산을 저장된 자료에서 (네트워크 없이)."""
    결과 = {"대출잔액": 0.0, "부동산공시": 0.0, "투자자산": 0.0, "메모": []}

    설정L = storage.불러오기("loan", None)
    if 설정L:
        try:
            from engines.loan import 스케줄_생성
            금리 = [{"start_month": r["시작회차"], "rate": r["금리(%)"]}
                  for r in (설정L.get("금리스케줄") or [])]
            if not any(r["start_month"] == 1 for r in 금리):
                금리.append({"start_month": 1, "rate": float(설정L.get("연이율", 3.5))})
            중도 = []
            for r in (설정L.get("중도상환목록") or []):
                try:
                    중도.append({"date": date.fromisoformat(str(r["날짜"])[:10]),
                               "amount": r["금액"], "method": r["방식"],
                               "interest": r.get("이자(직접입력)"),
                               "fee": r.get("수수료(직접입력)")})
                except Exception:  # noqa: BLE001
                    pass
            표, _경고 = 스케줄_생성(
                int(설정L["원금"]), date.fromisoformat(str(설정L["대출시작일"])[:10]),
                date.fromisoformat(str(설정L["첫납입일"])[:10]),
                int(설정L["상환개월수"]), 금리, 중도,
                설정L.get("상환방식", "원리금균등"),
                bool(설정L.get("영업일_적용", True)),
                설정L.get("이자정산방식", "원금분만"),
                float(설정L.get("수수료율", 0)), int(설정L.get("면제기간_개월", 36)))
            오늘 = date.today()
            남은 = [r for r in 표 if r["날짜"] >= 오늘 and r["구분"] == "정기납입"]
            결과["대출잔액"] = float(남은[0]["잔액"]) if 남은 else 0.0
            결과["메모"].append("대출 잔액 ← 🏦 대출 상환 계산기")
        except Exception as e:  # noqa: BLE001
            결과["메모"].append(f"대출 불러오기 실패 ({type(e).__name__})")

    자료P = storage.불러오기("property_tax", None)
    if 자료P and 자료P.get("부동산"):
        공시 = sum(float(p.get("공시가격(만원)") or 0) * 10000
                 * float(p.get("지분(%)") or 100) / 100
                 for p in 자료P["부동산"])
        결과["부동산공시"] = 공시
        결과["메모"].append("부동산 공시가격 ← 🏠 재산세 페이지")

    자료V = storage.불러오기("portfolio", None)
    if 자료V and 자료V.get("종목"):
        수동 = [x for x in 자료V["종목"]
              if x.get("현재가(수동)") or x.get("평가액(직접입력)")]
        if 수동:
            from engines import portfolio as PF
            종목들 = [PF.종목_계산(x, None, 1390.0) for x in 수동]
            결과["투자자산"] = float(PF.요약(종목들)["평가액"])
            결과["메모"].append(
                f"투자자산 ← 📊 자산배분 (수동 입력분 {len(수동)}/{len(자료V['종목'])}종목)")
    return 결과


자동 = 자동_수집()


# ==========================================================================
# 설정 불러오기 + 예전 형식 옮기기
# ==========================================================================
def _설정_정리(불러온: dict) -> tuple:
    """저장값을 이 버전 형식으로. (설정, 옮겼는지) 반환."""
    설정 = {k: (dict(v) if isinstance(v, dict) else
                (list(v) if isinstance(v, list) else v))
          for k, v in 기본설정.items()}
    설정.update({k: v for k, v in (불러온 or {}).items() if k in 기본설정})

    if 설정.get("형식") == 2 or 설정.get("자산표"):
        설정["형식"] = 2
        return 설정, False

    # 형식 표시가 없고 자산표도 없으면 예전 키에서 옮깁니다.
    옮긴것 = NW.옛설정_변환(설정, 자동)
    설정["자산표"] = 옮긴것 or NW.기본_자산표()
    설정["형식"] = 2
    return 설정, bool(옮긴것)


if "순자산_설정" not in st.session_state:
    설정, 옮겼음 = _설정_정리(storage.불러오기(저장키, {}) or {})
    st.session_state["순자산_설정"] = 설정
    st.session_state["순자산_옮김안내"] = 옮겼음
st.session_state.setdefault("순자산_표버전", 0)


def _설정_적용(데이터):
    설정, 옮겼음 = _설정_정리(데이터 or {})
    st.session_state["순자산_설정"] = 설정
    st.session_state["순자산_옮김안내"] = 옮겼음
    st.session_state["순자산_표버전"] += 1


불러온것_적용("_순자산_적용대기", _설정_적용)
설정 = st.session_state["순자산_설정"]
storage.임시서버_안내()

if st.session_state.pop("순자산_옮김안내", False):
    st.success(
        "예전에 저장하신 자료를 **소유자별 표**로 옮겼습니다. "
        "배우자 몫은 세부를 알 수 없어 '배우자 자산 합계' 한 줄로 넣었습니다. "
        "아래 표에서 예금·부동산처럼 쪼개시면 더 정확해집니다. "
        "확인하신 뒤 맨 아래 **저장** 을 눌러주세요.", icon="🔀")


# ==========================================================================
# 1. 자산 · 부채 표 (소유자 태그)
# ==========================================================================
ui.섹션("자산 · 부채", "줄마다 소유자를 고르세요. 공동명의는 **내 지분(%)** 에 "
                 "등기 지분율을 넣으면 그만큼만 내 몫이 됩니다.", 라벨="입력")

if 자동["메모"]:
    안내칸, 버튼칸 = st.columns([3, 1])
    안내칸.caption("다른 페이지에서 읽을 수 있는 값 — " + " · ".join(자동["메모"]))
    if 버튼칸.button("🔄 표에 반영", width="stretch",
                   help="정해진 이름의 줄을 찾아 금액만 갈아끼웁니다. "
                        "소유자·지분은 그대로 둡니다."):
        새것, 바뀐것 = NW.자동값_반영(설정["자산표"], 자동)
        설정["자산표"] = 새것
        st.session_state["순자산_표버전"] += 1
        st.session_state["순자산_반영결과"] = 바뀐것
        st.rerun()

바뀐것 = st.session_state.pop("순자산_반영결과", None)
if 바뀐것 is not None:
    if 바뀐것:
        st.success("반영했습니다 — " + " · ".join(바뀐것), icon="🔄")
    else:
        st.info("이미 같은 값이라 바뀐 줄이 없습니다.", icon="🔄")

열정의 = {"구분": "text", "항목": "text", "금액": "number", "소유자": "text",
        "내 지분(%)": "number", "만기일": "date", "메모": "text"}
기준표 = 표만들기(설정.get("자산표") or NW.기본_자산표(), 열정의)

편집표 = st.data_editor(
    기준표, num_rows="dynamic", width="stretch",
    key=f"순자산_자산표_{st.session_state['순자산_표버전']}",
    column_config={
        "구분": st.column_config.SelectboxColumn(
            options=NW.대분류_목록, width="small",
            help="비우면 항목 이름으로 짐작합니다. '부채' 로 두면 빼는 값이 됩니다."),
        "항목": st.column_config.TextColumn(width="medium"),
        "금액": st.column_config.NumberColumn(
            min_value=0, step=1_000_000, format="localized",
            help="부채도 **양수**로 넣으세요. 구분이 '부채' 면 알아서 뺍니다."),
        "소유자": st.column_config.SelectboxColumn(
            options=NW.소유자_목록, width="small", required=False),
        "내 지분(%)": st.column_config.NumberColumn(
            min_value=0, max_value=100, step=5, format="%.0f",
            help="'공동' 일 때만 씁니다. 비우면 반반(50%)으로 봅니다."),
        "만기일": st.column_config.DateColumn(
            format="YYYY-MM-DD", min_value=date(1990, 1, 1),
            max_value=date(2100, 12, 31),
            help="예금·적금 만기. 안 넣어도 됩니다."),
        "메모": st.column_config.TextColumn(width="medium"),
    })

새행들 = []
for _, row in 편집표.iterrows():
    만기 = 날짜로(row.get("만기일"))
    새행들.append({
        "구분": str(row.get("구분") or "").strip(),
        "항목": str(row.get("항목") or "").strip(),
        "금액": 숫자로(row.get("금액"), 0.0),
        "소유자": str(row.get("소유자") or "본인").strip(),
        "내 지분(%)": 숫자로(row.get("내 지분(%)"), 100.0),
        "만기일": (만기.isoformat() if 만기 else None),
        "메모": str(row.get("메모") or ""),
    })
설정["자산표"] = 새행들

집계 = NW.표_집계(새행들)
개인, 가족, 가구 = 집계["개인"], 집계["가족"], 집계["가구"]

if not 집계["쓴줄수"]:
    st.info("금액이 채워진 줄이 없습니다. 위 표에 금액을 넣으면 아래 계산이 "
            "나타납니다. 조사는 예금·전월세보증금·자동차·퇴직금까지 모두 "
            "포함하니 빠뜨리지 마세요.", icon="📝")
    st.divider()
    저장_불러오기(저장키, 설정, "순자산", "_순자산_적용대기",
              도움말="자산·부채 표와 순자산 기록이 함께 저장됩니다.")
    st.stop()

# 만기가 가까운 줄 알림
급한것 = [r for r in 집계["행들"]
        if r["만기일"] and NW.만기_급함(r["만기일"], 90)]
if 급한것:
    st.warning("**만기 임박** — " + " · ".join(
        f"{r['항목']} {NW.만기_표시(r['만기일'])} ({ui.억(r['금액'])})"
        for r in sorted(급한것, key=lambda r: str(r["만기일"]))[:5]), icon="⏰")


# ==========================================================================
# 2. 헤드라인 — 내 몫 / 가족 몫 / 가구
# ==========================================================================
개인백 = NW.백분위(개인["순자산"])
가구백 = NW.백분위(가구["순자산"])

st.divider()
ui.헤드라인(
    "가구 순자산 (우리 집 전체)",
    ui.억(가구["순자산"]),
    f"총자산 {ui.억(가구['총자산'])} − 부채 {ui.억(가구['총부채'])}",
    뱃지들=[ui.뱃지(f"전국 가구 상위 {가구백['상위']:.1f}%", "강조"),
          ui.뱃지(f"가구 평균의 {가구백['평균대비']:.0f}%", "중립")])

몫비율 = (개인["순자산"] / 가구["순자산"] * 100) if 가구["순자산"] else 0.0
ui.카드_줄([
    ("💙 내 몫 (개인)", ui.억(개인["순자산"]),
     f"가구의 {몫비율:.0f}% · 개인 기준 상위 {개인백['상위']:.1f}%", "파랑"),
    ("🧡 가족 몫", ui.억(가족["순자산"]),
     f"가구의 {100 - 몫비율:.0f}% · 배우자 명의 + 공동명의 중 내 지분 외", "주황"),
], 열수=2)
st.caption("**내 몫** = 본인 명의 전액 + 공동명의 중 내 지분. "
           "**가족 몫** = 가구 − 내 몫. 두 값을 더하면 가구 순자산이 됩니다.")

탭내몫, 탭비교, 탭추이 = st.tabs(["내 몫 · 가족 몫", "전국 비교", "추이"])


# ==========================================================================
# 탭 1 — 내 몫과 가족 몫이 어디에 들어 있나
# ==========================================================================
with 탭내몫:
    ui.섹션("세 기준 나란히 보기")
    st.dataframe(pd.DataFrame([
        {"기준": "💙 내 몫 (개인)", "총자산": round(개인["총자산"]),
         "총부채": round(개인["총부채"]), "순자산": round(개인["순자산"]),
         "부채비율(%)": round(개인["부채비율"], 1)},
        {"기준": "🧡 가족 몫", "총자산": round(가족["총자산"]),
         "총부채": round(가족["총부채"]), "순자산": round(가족["순자산"]),
         "부채비율(%)": round(가족["부채비율"], 1)},
        {"기준": "🏠 가구 합계", "총자산": round(가구["총자산"]),
         "총부채": round(가구["총부채"]), "순자산": round(가구["순자산"]),
         "부채비율(%)": round(가구["부채비율"], 1)},
    ]).style.format({"총자산": "{:,}", "총부채": "{:,}", "순자산": "{:,}",
                    "부채비율(%)": "{:.1f}"}),
                 width="stretch", hide_index=True)

    # ---- 대분류별로 내 몫/가족 몫 쌓아 보기 ----
    #  부채는 왼쪽(음수 방향)으로 그립니다. 자산과 같은 방향으로 그리면
    #  막대가 길수록 좋아 보여서 정반대로 읽히게 됩니다.
    if 집계["대분류별"]:
        ui.섹션("어느 항목에 누구 돈이 들어 있나",
              "오른쪽은 자산, 왼쪽은 부채입니다. 진한 파랑이 내 몫입니다.")
        구분들 = [d["구분"] for d in 집계["대분류별"]]
        부호 = [-1 if d["구분"] == "부채" else 1 for d in 집계["대분류별"]]
        막대 = go.Figure()
        막대.add_trace(go.Bar(
            y=구분들, x=[s * d["개인"] / 1e8 for s, d in zip(부호, 집계["대분류별"])],
            name="내 몫", orientation="h", marker_color=ui.색["파랑"],
            hovertemplate="%{y} · 내 몫 %{customdata:.2f}억<extra></extra>",
            customdata=[d["개인"] / 1e8 for d in 집계["대분류별"]]))
        막대.add_trace(go.Bar(
            y=구분들, x=[s * d["가족"] / 1e8 for s, d in zip(부호, 집계["대분류별"])],
            name="가족 몫", orientation="h", marker_color=ui.색["주황"],
            hovertemplate="%{y} · 가족 몫 %{customdata:.2f}억<extra></extra>",
            customdata=[d["가족"] / 1e8 for d in 집계["대분류별"]]))
        막대.add_vline(x=0, line_color="rgba(128,128,128,.6)")
        막대.update_layout(barmode="relative", height=max(240, 46 * len(구분들) + 90),
                         margin=dict(l=10, r=10, t=34, b=10),
                         xaxis_title="금액(억) — 왼쪽은 부채",
                         legend=dict(orientation="h", y=1.16))
        ui.차트(막대)

        st.dataframe(pd.DataFrame([
            {"구분": d["구분"], "가구 전체": round(d["가구"]),
             "내 몫": round(d["개인"]), "가족 몫": round(d["가족"]),
             "내 비중(%)": round(d["개인"] / d["가구"] * 100, 1) if d["가구"] else 0.0}
            for d in 집계["대분류별"]
        ]).style.format({"가구 전체": "{:,}", "내 몫": "{:,}", "가족 몫": "{:,}",
                        "내 비중(%)": "{:.1f}"}),
                     width="stretch", hide_index=True)

    # ---- 명의별 총자산 ----
    명의 = [(s, 집계["소유자별"][s]["자산"]) for s in NW.소유자_목록
          if 집계["소유자별"][s]["자산"] > 0]
    if len(명의) > 1:
        ui.섹션("누구 명의인가", "총자산 기준입니다. '공동' 은 전액으로 셉니다.")
        도넛 = go.Figure(go.Pie(
            labels=[m[0] for m in 명의], values=[m[1] for m in 명의], hole=0.62,
            marker=dict(colors=[NW.소유자_색[m[0]] for m in 명의]),
            texttemplate="%{label}<br>%{percent}", textposition="outside",
            hovertemplate="%{label} %{value:,.0f}원 (%{percent})<extra></extra>"))
        도넛.update_layout(height=290, margin=dict(l=10, r=10, t=16, b=10),
                         showlegend=False, paper_bgcolor="rgba(0,0,0,0)")
        ui.차트(도넛, 테마=False)

    # ---- 줄별 상세 ----
    with st.expander("📄 줄별 상세 (내 몫 / 가족 몫)"):
        상세 = pd.DataFrame([{
            "구분": r["구분"], "항목": r["항목"], "소유자": r["소유자"],
            "지분(%)": r["내 지분(%)"],
            "금액": round(r["금액"]) * (-1 if r["부채"] else 1),
            "내 몫": round(r["내몫"]) * (-1 if r["부채"] else 1),
            "가족 몫": round(r["가족몫"]) * (-1 if r["부채"] else 1),
            "만기": NW.만기_표시(r["만기일"]),
        } for r in 집계["행들"]])
        st.dataframe(상세.style.format({"금액": "{:+,}", "내 몫": "{:+,}",
                                      "가족 몫": "{:+,}", "지분(%)": "{:.0f}"}),
                     width="stretch", hide_index=True)
        st.caption("부채는 −로 표시했습니다. 표에 넣으실 때는 양수로 넣으세요.")

    with st.expander("ℹ️ 소유자를 어떻게 정하나요"):
        st.markdown(
            "- **본인** — 내 명의. 개인·가구 양쪽에 전액 들어갑니다.\n"
            "- **배우자** — 배우자 명의. 가구에만 들어가고 내 몫에는 0입니다.\n"
            "- **공동** — 공동명의. **내 지분(%)** 만큼만 내 몫이 됩니다. "
            "등기 지분이 6:4 면 60 을 넣으세요. 안 적으면 반반으로 봅니다.\n\n"
            "부부 공동명의 집에 걸린 주택담보대출도 같은 방식으로 나눕니다. "
            "지분 60%면 대출도 60%가 내 부채로 잡혀서, 자산만 나누고 부채는 "
            "안 나누는 데서 오는 왜곡이 생기지 않습니다.")


# ==========================================================================
# 탭 2 — 전국 비교
# ==========================================================================
with 탭비교:
    ui.섹션("전국에서 어디쯤인가",
          "가구 기준이 공식 비교값입니다. 개인 기준은 참고용입니다.")

    ui.카드_줄([
        ("🏠 가구 순자산", ui.억(가구["순자산"]),
         f"상위 {가구백['상위']:.1f}% · {가구백['정확도']}", "초록"),
        ("💙 내 몫 (참고용)", ui.억(개인["순자산"]),
         f"상위 {개인백['상위']:.1f}% · 개인 분포 공식 통계 없음", "파랑"),
        ("총자산", ui.억(가구["총자산"]), f"부채 {ui.억(가구['총부채'])}"),
        ("부채비율", f"{가구['부채비율']:.1f}%", "가구 총부채 ÷ 총자산"),
    ], 열수=2)

    곡선 = go.Figure()
    xs = [1e7 * (1.35 ** i) for i in range(28)]
    곡선.add_trace(go.Scatter(
        x=[v / 1e8 for v in xs], y=[NW.백분위(v)["상위"] for v in xs],
        mode="lines", line=dict(color=ui.색["회색"], width=2), name="전국 분포",
        hovertemplate="%{x:.1f}억 → 상위 %{y:.1f}%<extra></extra>"))
    for 값, 라벨, 색이름 in [(개인["순자산"], "내 몫", "파랑"),
                        (가구["순자산"], "가구", "초록")]:
        if 값 > 0:
            곡선.add_trace(go.Scatter(
                x=[값 / 1e8], y=[NW.백분위(값)["상위"]], mode="markers+text",
                marker=dict(size=14, color=ui.색[색이름]), text=[라벨],
                textposition="top center", name=라벨,
                hovertemplate=f"{라벨} %{{x:.2f}}억 → 상위 %{{y:.1f}}%<extra></extra>"))
    곡선.add_hline(y=50, line_dash="dot", line_color="rgba(140,140,140,.6)",
                 annotation_text="중간(상위 50%)", annotation_position="top left")
    # 로그 축은 그냥 두면 눈금 사이 보조 눈금까지 숫자가 붙어서
    # "0.1 2 5 1 2 5 10 2 5 100" 처럼 읽을 수 없게 됩니다. 직접 정합니다.
    곡선.update_layout(height=340, margin=dict(l=10, r=14, t=30, b=10),
                     xaxis=dict(title="순자산(억)", type="log",
                                tickmode="array",
                                tickvals=[0.1, 0.3, 1, 3, 10, 30, 100],
                                ticktext=["0.1억", "0.3억", "1억", "3억",
                                          "10억", "30억", "100억"]),
                     yaxis=dict(title="상위 %", autorange="reversed"),
                     legend=dict(orientation="h", y=1.15))
    ui.차트(곡선)

    st.dataframe(pd.DataFrame([
        {"기준": "가구 (공식 기준)", "순자산": round(가구["순자산"]),
         "상위(%)": round(가구백["상위"], 1),
         "가구평균 대비(%)": round(가구백["평균대비"]), "정확도": 가구백["정확도"]},
        {"기준": "개인 (참고용)", "순자산": round(개인["순자산"]),
         "상위(%)": round(개인백["상위"], 1),
         "가구평균 대비(%)": round(개인백["평균대비"]), "정확도": 개인백["정확도"]},
    ]).style.format({"순자산": "{:,}", "상위(%)": "{:.1f}",
                    "가구평균 대비(%)": "{:.0f}"}),
                 width="stretch", hide_index=True)

    with st.expander("ℹ️ 비교가 왜곡되는 이유"):
        st.warning(
            "**개인 기준 백분위는 참고용입니다.** 가계금융복지조사는 가구 단위 "
            "통계이고, 개인 순자산 분포의 공식 통계는 없습니다. 개인 값을 가구 "
            "분포에 그대로 대보면 실제 위치보다 낮게 나옵니다. 순위를 보실 때는 "
            "**가구 기준**을 쓰세요.\n\n"
            f"참고 — {NW.조사연도}년 조사 기준 가구 평균 순자산 "
            f"{ui.억(NW.가구평균_순자산)}, 전체의 57%가 3억 미만, 10억 이상은 "
            "11.8% 입니다. 백분위 곡선은 공표된 몇 개 지점을 보간한 "
            "**추정치**입니다.", icon="📊")
        st.caption(
            "**흔한 왜곡 네 가지** — ① 개인 자산만 넣고 가구 통계와 비교 "
            "② 예금·보증금·자동차를 빼먹음 ③ 부동산을 시세가 아닌 공시가격으로 "
            "넣음 ④ 연령을 무시한 비교. 조사에서 가구주 50~59세 가구의 순자산이 "
            "5억 5,161만원으로 연령대 중 가장 높았습니다. 30대와 50대를 같은 "
            "잣대로 보시면 안 됩니다.")


# ==========================================================================
# 탭 3 — 추이
# ==========================================================================
with 탭추이:
    ui.섹션("얼마나 빨리 늘고 있나",
          "기록을 두 개 이상 남기면 증감 속도가 계산됩니다.")

    기준선택 = ui.선택줄("보는 기준", ["가구 순자산", "내 몫 (개인)"],
                    key="순자산_기록기준",
                    기본=0 if 설정.get("기록기준", "가구") == "가구" else 1)
    설정["기록기준"] = "가구" if 기준선택.startswith("가구") else "개인"
    값열 = "순자산" if 설정["기록기준"] == "가구" else "개인순자산"

    기록 = list(설정.get("기록") or [])
    기록열 = {"날짜": "date", "순자산": "number", "개인순자산": "number",
            "메모": "text"}
    기록df = st.data_editor(
        표만들기(기록, 기록열), num_rows="dynamic", width="stretch",
        key=f"순자산_기록_{st.session_state['순자산_표버전']}",
        column_config={
            "날짜": st.column_config.DateColumn(format="YYYY-MM-DD",
                                              min_value=date(1990, 1, 1),
                                              max_value=date(2100, 12, 31)),
            "순자산": st.column_config.NumberColumn(
                "가구 순자산", min_value=0, step=1_000_000, format="localized"),
            "개인순자산": st.column_config.NumberColumn(
                "내 몫 (개인)", min_value=0, step=1_000_000, format="localized",
                help="비워두셔도 됩니다. 가구 기준만으로도 추이는 나옵니다."),
            "메모": st.column_config.TextColumn(),
        })

    c3, c4 = st.columns([1, 1])
    if c3.button("📌 오늘 기록에 추가", type="primary", width="stretch"):
        새기록 = [r for r in 기록 if str(r.get("날짜"))[:10] != date.today().isoformat()]
        새기록.append({"날짜": date.today().isoformat(),
                    "순자산": int(가구["순자산"]),
                    "개인순자산": int(개인["순자산"]), "메모": ""})
        설정["기록"] = sorted(새기록, key=lambda r: str(r["날짜"]))
        st.session_state["순자산_표버전"] += 1
        성공, 메시지 = storage.저장하기(저장키, 설정)
        (st.success if 성공 else st.error)(메시지)
        st.rerun()
    c4.caption(f"오늘 날짜로 가구 {ui.억(가구['순자산'])} · "
               f"내 몫 {ui.억(개인['순자산'])} 을 함께 남깁니다.")

    with st.expander("📋 엑셀에서 복사해 붙여넣기", expanded=False):
        st.caption(
            "엑셀에서 **머리글 줄까지 포함해** 범위를 복사한 뒤 아래에 붙여넣으세요. "
            "`기준월`(또는 `날짜`) 과 `순자산` 열을 찾아 읽습니다. "
            "나머지 열은 무시하니 통째로 복사하셔도 됩니다. "
            "읽어들인 값은 **가구 순자산**으로 넣습니다.")
        st.code("기준월\t예금\t...\t총자산\t순자산\t전월대비\n"
                "2026-06-30\t144,592,350원\t...\t1,166,057,532원\t810,891,235원\t4,938,780원",
                language=None)
        붙임 = st.text_area("붙여넣기", height=160, key="_순자산_붙임",
                          placeholder="여기에 Ctrl+V")

        b1, b2 = st.columns(2)
        합치기 = b1.radio("기존 기록은", ["합치기 (같은 날짜는 덮어씀)", "모두 지우고 새로"],
                      key="_붙임방식")
        if b2.button("📥 읽어들이기", type="primary", width="stretch",
                     disabled=not 붙임.strip()):
            새기록, 경고들 = NW.붙여넣기_읽기(붙임)
            for m in 경고들:
                st.warning(m, icon="⚠️")
            if 새기록:
                if 합치기.startswith("모두"):
                    합본 = 새기록
                else:
                    묶 = {str(r["날짜"])[:10]: r for r in 기록}
                    for r in 새기록:
                        키 = str(r["날짜"])[:10]
                        # 이미 있던 줄의 '내 몫' 은 지우지 않고 이어받습니다
                        기존 = 묶.get(키) or {}
                        r = dict(r)
                        r.setdefault("개인순자산", 기존.get("개인순자산"))
                        묶[키] = r
                    합본 = sorted(묶.values(), key=lambda r: str(r["날짜"]))
                설정["기록"] = 합본
                st.session_state["순자산_표버전"] += 1
                성공, 메시지 = storage.저장하기(저장키, 설정)
                st.success(f"{len(새기록)}줄을 읽었습니다. (전체 {len(합본)}줄)  {메시지}")
                st.rerun()

        st.caption(
            "괄호는 음수로 읽습니다 — `(355,166,297원)` → **−355,166,297**. "
            "`원` `₩` 쉼표는 알아서 떼고, `-` 나 빈칸은 0 으로 봅니다.")

    읽은기록 = []
    for _, row in 기록df.iterrows():
        d = 날짜로(row.get("날짜"))
        가구값 = row.get("순자산")
        if d is None or pd.isna(가구값):
            continue
        개인값 = row.get("개인순자산")
        읽은기록.append({
            "날짜": d.isoformat(),
            "순자산": float(가구값),
            "개인순자산": (None if pd.isna(개인값) else float(개인값)),
            "순납입액": 0.0,
            "메모": str(row.get("메모") or ""),
        })
    설정["기록"] = 읽은기록

    # 고른 기준으로 추이를 계산합니다. 개인 기준을 골랐는데 '내 몫' 이
    # 비어 있는 줄은 쓸 수 없으므로 빼고 셉니다.
    분석대상 = [{"날짜": r["날짜"], "순자산": r[값열], "순납입액": 0.0}
            for r in 읽은기록 if r.get(값열) is not None]
    추이 = NW.추이_분석(분석대상)
    기준이름 = "가구 순자산" if 설정["기록기준"] == "가구" else "내 몫(개인)"

    if 설정["기록기준"] == "개인" and len(분석대상) < len(읽은기록):
        st.caption(f"'내 몫' 이 비어 있는 {len(읽은기록) - len(분석대상)}줄은 "
                   "개인 기준 계산에서 빠졌습니다.")

    if not 추이["충분"]:
        st.info(f"{기준이름} 기록이 {추이['기록수']}개입니다. **2개 이상**이어야 "
                "증감 속도를 계산할 수 있습니다. 위 **오늘 기록에 추가** 를 눌러 "
                "시작하시고, 분기나 반기마다 한 번씩 남기시면 됩니다.", icon="📝")
    else:
        e = 추이["전체"]
        ui.카드_줄([
            (f"전체 증감 ({기준이름})", ui.부호억(e["총증감"]),
             f"{ui.억(e['시작'])} → {ui.억(e['끝'])} ({e['년']:.1f}년)",
             "초록" if e["총증감"] >= 0 else "빨강"),
            ("전체 성장률", f"{e['성장률']:+.1f}%", f"{e['년']:.1f}년 누적"),
            ("연평균(CAGR)", f"{e['CAGR']:+.2f}%",
             (f"이 속도면 2배까지 {추이['배가기간']:.1f}년" if 추이["배가기간"]
              else "감소 중")),
            ("월평균 증감", ui.부호억(e["총증감"] / max(e["일수"] / 30.44, 1)),
             "기간 평균"),
        ], 열수=2)

        # 가구선과 개인선을 함께 그립니다. 벌어지는 폭이 곧 '가족 몫' 입니다.
        추이그림 = go.Figure()
        날짜들 = [NW._날짜(r["날짜"]) for r in 읽은기록]
        추이그림.add_trace(go.Scatter(
            x=날짜들, y=[r["순자산"] / 1e8 for r in 읽은기록],
            mode="lines+markers", line=dict(color=ui.색["초록"], width=3),
            name="가구 순자산",
            hovertemplate="%{x|%Y-%m-%d}<br>가구 %{y:.2f}억<extra></extra>"))
        개인점 = [(d, r["개인순자산"] / 1e8) for d, r in zip(날짜들, 읽은기록)
               if r.get("개인순자산") is not None]
        if 개인점:
            추이그림.add_trace(go.Scatter(
                x=[p[0] for p in 개인점], y=[p[1] for p in 개인점],
                mode="lines+markers", line=dict(color=ui.색["파랑"], width=3),
                name="내 몫(개인)",
                hovertemplate="%{x|%Y-%m-%d}<br>내 몫 %{y:.2f}억<extra></extra>"))
        추이그림.update_layout(height=330, margin=dict(l=10, r=10, t=34, b=10),
                           yaxis_title="순자산(억)", hovermode="x unified",
                           legend=dict(orientation="h", y=1.16))
        ui.차트(추이그림)
        if 개인점:
            st.caption("두 선의 간격이 **가족 몫**입니다. 간격이 벌어지면 "
                       "가구는 늘었지만 내 몫은 그만큼 늘지 않은 것입니다.")

        라벨 = [f"{g['종료일']:%y.%m}" for g in 추이["구간들"]]
        증감값 = [g["총증감"] / 1e4 for g in 추이["구간들"]]
        분해 = go.Figure(go.Bar(
            x=라벨, y=증감값,
            marker_color=[ui.색["초록"] if v >= 0 else ui.색["빨강"] for v in 증감값],
            hovertemplate="%{x}<br>%{y:+,.0f}만원<extra></extra>"))
        분해.add_hline(y=0, line_color="rgba(140,140,140,.8)")
        분해.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10),
                         yaxis_title=f"기간별 증감(만원) · {기준이름}",
                         showlegend=False)
        ui.차트(분해)

        구간표 = pd.DataFrame([{
            "구간": f"{g['시작일']} → {g['종료일']}",
            "순자산": round(g["끝"]),
            "증감": round(g["총증감"]),
            "성장률(%)": round(g["성장률"], 2),
            "연율(CAGR %)": round(g["CAGR"], 2),
            "일수": g["일수"],
        } for g in 추이["구간들"]])
        st.dataframe(구간표.style.format(
            {"순자산": "{:,}", "증감": "{:+,}",
             "성장률(%)": "{:+.2f}", "연율(CAGR %)": "{:+.2f}"}),
            width="stretch", hide_index=True)

        급여 = storage.불러오기("salary", None)
        if 급여:
            try:
                from engines import salary as S
                기록들 = S.dashboard_records(급여)
                if 기록들:
                    연봉 = 기록들[-1]["base_sal"]
                    a = NW.소득대비_축적(e, 연봉)
                    if a:
                        with st.expander("ℹ️ 연봉 대비 수치의 뜻"):
                            st.caption(
                                f"💰 연봉 관리 자료 연계 — {기록들[-1]['year']}년 연봉 "
                                f"{ui.억(연봉)} 기준으로 {기준이름}이 **연평균 "
                                f"{ui.억(a['연간증가'])}** 씩 늘었습니다 "
                                f"(연봉의 {a['연봉대비']:.0f}%). "
                                f"현재는 연봉의 {a['연봉배수']:.1f}배입니다.\n\n"
                                "※ 저축률이 아닙니다. 시장 수익이 포함된 값이라 "
                                "연봉을 넘을 수도 있습니다.")
            except Exception:  # noqa: BLE001
                pass

        with st.expander("ℹ️ '작년보다 20% 늘었다' 를 어떻게 읽나"):
            st.info(
                "**증감만으로는 실력인지 장세인지 알 수 없습니다.** 저축은 통제할 "
                "수 있고 시장수익은 통제할 수 없습니다. 시장이 좋았던 해에 저축을 "
                "게을리했다면 총증감은 커 보여도 실제로는 뒷걸음질일 수 있습니다.\n\n"
                "**가구와 내 몫을 함께 보세요.** 가구 순자산이 늘어도 늘어난 쪽이 "
                "배우자 명의라면 내 몫은 그대로입니다. 위 차트에서 두 선의 간격이 "
                "그걸 보여줍니다.", icon="🔍")


st.divider()
저장_불러오기(저장키, 설정, "순자산", "_순자산_적용대기",
          도움말="소유자별 자산·부채 표와 순자산 기록(가구·개인)이 함께 저장됩니다.")
