import os
import sys
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import 불러온것_적용, 저장_불러오기  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import networth as NW  # noqa: E402

require_login(page_title="순자산", page_icon="💎", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("💎 순자산 · 백분위 · 증감 속도")
st.caption(f"기준 통계: 「{NW.조사연도}년 가계금융복지조사」 ({NW.조사기준일})")

저장키 = "networth"
기본설정 = {
    "기타자산": {}, "기타부채": {}, "배우자자산": 0, "배우자부채": 0,
    "부동산시세": 0, "기록": [],
}

if "순자산_설정" not in st.session_state:
    불러온 = storage.불러오기(저장키, {}) or {}
    설정 = dict(기본설정)
    설정.update({k: v for k, v in 불러온.items() if k in 기본설정})
    st.session_state["순자산_설정"] = 설정
st.session_state.setdefault("순자산_표버전", 0)


def _설정_적용(데이터):
    새것 = dict(기본설정)
    새것.update({k: v for k, v in (데이터 or {}).items() if k in 기본설정})
    st.session_state["순자산_설정"] = 새것
    st.session_state["순자산_표버전"] += 1


불러온것_적용("_순자산_적용대기", _설정_적용)
설정 = st.session_state["순자산_설정"]
storage.임시서버_안내()


# ==========================================================================
# 다른 페이지에서 자동으로 끌어오기
# ==========================================================================
@st.cache_data(ttl=600, show_spinner=False)
def 자동_수집():
    """대출 잔액과 부동산 공시가격을 저장된 자료에서 가져옵니다 (네트워크 없이)."""
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
            결과["메모"].append("대출 잔액: 🏦 대출 상환 계산기")
        except Exception as e:  # noqa: BLE001
            결과["메모"].append(f"대출 불러오기 실패 ({type(e).__name__})")

    자료P = storage.불러오기("property_tax", None)
    if 자료P and 자료P.get("부동산"):
        공시 = sum(float(p.get("공시가격(만원)") or 0) * 10000
                 * float(p.get("지분(%)") or 100) / 100
                 for p in 자료P["부동산"])
        결과["부동산공시"] = 공시
        결과["메모"].append("부동산 공시가격: 🏠 재산세 페이지")

    자료V = storage.불러오기("portfolio", None)
    if 자료V and 자료V.get("종목"):
        수동 = [x for x in 자료V["종목"]
              if x.get("현재가(수동)") or x.get("평가액(직접입력)")]
        if 수동:
            from engines import portfolio as PF
            종목들 = [PF.종목_계산(x, None, 1390.0) for x in 수동]
            결과["투자자산"] = float(PF.요약(종목들)["평가액"])
            결과["메모"].append(
                f"투자자산: 📊 자산배분 (수동 입력분 {len(수동)}/{len(자료V['종목'])}종목만)")
    return 결과


자동 = 자동_수집()

# ==========================================================================
# 입력
# ==========================================================================
st.subheader("1. 자산 · 부채")
if 자동["메모"]:
    st.caption("자동으로 가져온 것 — " + " · ".join(자동["메모"]))

c1, c2 = st.columns(2)
투자자산 = c1.number_input("투자자산(원)", min_value=0, step=1_000_000,
                      value=int(자동["투자자산"]),
                      help="📊 자산배분 페이지에서 가져옵니다. 시세 조회분은 빠져 있으니 "
                           "정확한 값을 직접 넣으셔도 됩니다.")
대출잔액 = c2.number_input("주택담보대출 잔액(원)", min_value=0, step=1_000_000,
                      value=int(자동["대출잔액"]))

부동산기본 = int(설정.get("부동산시세") or 자동["부동산공시"] * 1.45)
부동산 = st.number_input("부동산 시세(원)", min_value=0, step=10_000_000,
                     value=부동산기본,
                     help="공시가격이 아니라 **시세**를 넣으세요. 조사가 시세 기준이라 "
                          "공시가격을 넣으면 순자산이 실제보다 작게 나옵니다.")
if 자동["부동산공시"]:
    with st.expander("ℹ️ 자세히"):
        st.caption(f"재산세 페이지의 공시가격 합계는 {ui.억(자동['부동산공시'])} 입니다. "
                   f"공시가격은 보통 시세의 60~70% 수준이라 위 칸에는 "
                   f"{ui.억(자동['부동산공시'] * 1.45)} 안팎을 넣으시면 얼추 맞습니다. "
                   "실거래가를 아시면 그 값이 정확합니다.")

with st.expander("➕ 빠진 자산 · 부채 넣기", expanded=False):
    st.caption("조사는 예금·보증금·자동차까지 다 포함합니다. 안 넣으면 순자산이 "
               "실제보다 작게 나와 백분위도 낮게 나옵니다.")
    기타자산 = {}
    for 이름, 도움 in NW.기타자산_항목:
        기타자산[이름] = st.number_input(
            이름, min_value=0, step=1_000_000,
            value=int((설정.get("기타자산") or {}).get(이름, 0)),
            help=도움, key=f"_자산_{이름}")
    st.markdown("---")
    기타부채 = {}
    for 이름, 도움 in NW.기타부채_항목:
        기타부채[이름] = st.number_input(
            이름, min_value=0, step=1_000_000,
            value=int((설정.get("기타부채") or {}).get(이름, 0)),
            help=도움, key=f"_부채_{이름}")

집계 = NW.순자산_계산(투자자산, 부동산, 대출잔액, 기타자산, 기타부채)

st.subheader("2. 가구 기준 (배우자 합산)")
st.caption("이 통계는 **가구 단위**입니다. 개인 자산만 비교하면 실제보다 낮게 나옵니다.")
b1, b2 = st.columns(2)
배우자자산 = b1.number_input("배우자 자산(원)", min_value=0, step=10_000_000,
                       value=int(설정.get("배우자자산") or 0))
배우자부채 = b2.number_input("배우자 부채(원)", min_value=0, step=1_000_000,
                       value=int(설정.get("배우자부채") or 0))

가구순자산 = 집계["순자산"] + 배우자자산 - 배우자부채

설정.update({
    "기타자산": {k: int(v) for k, v in 기타자산.items() if v},
    "기타부채": {k: int(v) for k, v in 기타부채.items() if v},
    "배우자자산": int(배우자자산), "배우자부채": int(배우자부채),
    "부동산시세": int(부동산),
})

# ==========================================================================

# ==========================================================================
# 탭으로 묶기 (탭 2개)
# ==========================================================================
# 한 줄 요약
_개인백 = NW.백분위(개인순자산)
_가구백 = NW.백분위(가구순자산)
st.markdown(
    f"### {ui.억(가구순자산)} "
    f"<span style='font-size:.62em;opacity:.75'>"
    f"가구 상위 {_가구백['상위']:.1f}% · 개인 상위 {_개인백['상위']:.1f}% · "
    f"총자산 {ui.억(합계['총자산'])} · 부채 {ui.억(합계['총부채'])}</span>",
    unsafe_allow_html=True)

탭비교, 탭추이 = st.tabs(["비교", "추이"])

with 탭비교:
    # 백분위
    # ==========================================================================
    st.subheader("전국에서 어디쯤인가")

    개인 = NW.백분위(집계["순자산"])
    가구 = NW.백분위(가구순자산)

    ui.카드_줄([
        ("개인 순자산", ui.억(집계["순자산"]), f"상위 {개인['상위']:.1f}% (참고용)"),
        ("가구 순자산", ui.억(가구순자산), f"상위 {가구['상위']:.1f}% (공식 기준)"),
        ("총자산", ui.억(집계["총자산"]), f"부채 {ui.억(집계['총부채'])}"),
        ("부채비율", f"{집계['부채비율']:.1f}%", "총부채 ÷ 총자산"),
    ], 열수=2)

    곡선 = go.Figure()
    xs = [1e7 * (1.35 ** i) for i in range(28)]
    곡선.add_trace(go.Scatter(
        x=[v / 1e8 for v in xs], y=[NW.백분위(v)["상위"] for v in xs],
        mode="lines", line=dict(color="#9AA3AF", width=2), name="전국 분포",
        hovertemplate="%{x:.1f}억 → 상위 %{y:.1f}%<extra></extra>"))
    for 값, 라벨, 색 in [(집계["순자산"], "개인", "#2B6ED5"),
                      (가구순자산, "가구", "#C0392B")]:
        if 값 > 0:
            곡선.add_trace(go.Scatter(
                x=[값 / 1e8], y=[NW.백분위(값)["상위"]], mode="markers+text",
                marker=dict(size=14, color=색), text=[라벨], textposition="top center",
                name=라벨, hovertemplate=f"{라벨} %{{x:.2f}}억 → 상위 %{{y:.1f}}%<extra></extra>"))
    곡선.add_hline(y=50, line_dash="dot", line_color="rgba(140,140,140,.6)",
                 annotation_text="중간(상위 50%)", annotation_position="right")
    곡선.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                     xaxis=dict(title="순자산(억)", type="log"),
                     yaxis=dict(title="상위 %", autorange="reversed"),
                     legend=dict(orientation="h", y=1.15))
    st.plotly_chart(곡선, width="stretch")

    st.dataframe(pd.DataFrame([
        {"기준": "개인 (참고용)", "순자산": round(집계["순자산"]),
         "상위(%)": round(개인["상위"], 1), "가구평균 대비(%)": round(개인["평균대비"]),
         "정확도": 개인["정확도"]},
        {"기준": "가구 (공식 기준)", "순자산": round(가구순자산),
         "상위(%)": round(가구["상위"], 1), "가구평균 대비(%)": round(가구["평균대비"]),
         "정확도": 가구["정확도"]},
    ]).style.format({"순자산": "{:,}", "상위(%)": "{:.1f}",
                    "가구평균 대비(%)": "{:.0f}"}),
                 width="stretch", hide_index=True)

    with st.expander("ℹ️ 비교가 왜곡되는 이유"):
        st.warning(
            "**개인 기준 백분위는 참고용입니다.** 가계금융복지조사는 가구 단위 통계이고, "
            "개인 순자산 분포의 공식 통계는 없습니다. 개인 값을 가구 분포에 그대로 대보면 "
            "실제 위치보다 낮게 나옵니다. 비교하시려면 **가구 기준**을 보세요.\\n\\n"
            f"참고 — {NW.조사연도}년 조사 기준 가구 평균 순자산 "
            f"{ui.억(NW.가구평균_순자산)}, 전체의 57%가 3억 미만, 10억 이상은 11.8% 입니다. "
            "백분위 곡선은 공표된 몇 개 지점을 보간한 **추정치**입니다.", icon="📊")

    # ==========================================================================

with 탭추이:
    # 증감 속도
    # ==========================================================================
    st.subheader("얼마나 빨리 늘고 있나")

    기록 = list(설정.get("기록") or [])
    기준df = pd.DataFrame(기록, columns=["날짜", "순자산", "메모"])
    기준df["날짜"] = pd.Series(
        [None if pd.isna(v) else (v if isinstance(v, date)
                                  else pd.to_datetime(v, errors="coerce").date()
                                  if pd.notna(pd.to_datetime(v, errors="coerce")) else None)
         for v in 기준df["날짜"]], dtype="object")
    기준df["순자산"] = pd.to_numeric(기준df["순자산"], errors="coerce")

    기록df = st.data_editor(
        기준df, num_rows="dynamic", width="stretch",
        key=f"순자산_기록_{st.session_state.get('순자산_표버전', 0)}",
        column_config={
            "날짜": st.column_config.DateColumn(format="YYYY-MM-DD",
                                              min_value=date(1990, 1, 1),
                                              max_value=date(2100, 12, 31)),
            "순자산": st.column_config.NumberColumn(min_value=0, step=1_000_000,
                                                format="%.0f"),
            "메모": st.column_config.TextColumn(),
        })

    c3, c4 = st.columns(2)
    if c3.button("📌 오늘 순자산 기록에 추가", type="primary", width="stretch"):
        새기록 = [r for r in 기록 if str(r.get("날짜"))[:10] != date.today().isoformat()]
        새기록.append({"날짜": date.today().isoformat(),
                    "순자산": int(가구순자산), "메모": ""})
        설정["기록"] = sorted(새기록, key=lambda r: str(r["날짜"]))
        st.session_state["순자산_표버전"] += 1
        성공, 메시지 = storage.저장하기(저장키, 설정)
        (st.success if 성공 else st.error)(메시지)
        st.rerun()
    c4.caption("가구 순자산 기준으로 오늘 날짜를 추가합니다.")

    with st.expander("📋 엑셀에서 복사해 붙여넣기", expanded=False):
        st.caption(
            "엑셀에서 **머리글 줄까지 포함해** 범위를 복사한 뒤 아래에 붙여넣으세요. "
            "`기준월`(또는 `날짜`) 과 `순자산` 열을 찾아 읽습니다. "
            "나머지 열은 무시하니 통째로 복사하셔도 됩니다.")
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
                    묶.update({str(r["날짜"])[:10]: r for r in 새기록})
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
        d, v = row.get("날짜"), row.get("순자산")
        if d is None or pd.isna(d) or pd.isna(v):
            continue
        읽은기록.append({
            "날짜": (d.isoformat() if isinstance(d, date) else str(d)[:10]),
            "순자산": float(v),
            "순납입액": 0.0,
            "메모": str(row.get("메모") or ""),
        })
    설정["기록"] = 읽은기록

    추이 = NW.추이_분석(읽은기록)

    if not 추이["충분"]:
        with st.expander("ℹ️ 자세히"):
            st.info(f"기록이 {추이['기록수']}개입니다. **2개 이상**이어야 증감 속도를 "
                    "계산할 수 있습니다. 위 **오늘 순자산 기록에 추가** 를 눌러 시작하시고, "
                    "분기나 반기마다 한 번씩 남기시면 됩니다.", icon="📝")
    else:
        e = 추이["전체"]
        ui.카드_줄([
            ("전체 증감", ui.억(e["총증감"]),
             f"{ui.억(e['시작'])} → {ui.억(e['끝'])} ({e['년']:.1f}년)"),
            ("전체 성장률", f"{e['성장률']:+.1f}%",
             f"{e['년']:.1f}년 누적"),
            ("연평균(CAGR)", f"{e['CAGR']:+.2f}%",
             (f"이 속도면 2배까지 {추이['배가기간']:.1f}년" if 추이["배가기간"]
              else "감소 중")),
            ("월평균 증감", ui.억(e["총증감"] / max(e["일수"] / 30.44, 1)),
             "기간 평균"),
        ], 열수=2)

        추이그림 = go.Figure()
        날짜들 = [NW._날짜(r["날짜"]) for r in 읽은기록]
        추이그림.add_trace(go.Scatter(
            x=날짜들, y=[r["순자산"] / 1e8 for r in 읽은기록],
            mode="lines+markers", line=dict(color="#2B6ED5", width=3),
            fill="tozeroy", fillcolor="rgba(43,110,213,.10)", name="순자산",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}억<extra></extra>"))
        추이그림.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                           yaxis_title="순자산(억)", hovermode="x unified")
        st.plotly_chart(추이그림, width="stretch")

        라벨 = [f"{g['종료일']:%y.%m}" for g in 추이["구간들"]]
        증감값 = [g["총증감"] / 1e4 for g in 추이["구간들"]]
        분해 = go.Figure(go.Bar(
            x=라벨, y=증감값,
            marker_color=["#18A57A" if v >= 0 else "#C0392B" for v in 증감값],
            hovertemplate="%{x}<br>%{y:+,.0f}만원<extra></extra>"))
        분해.add_hline(y=0, line_color="rgba(140,140,140,.8)")
        분해.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                         yaxis_title="기간별 증감(만원)", showlegend=False)
        st.plotly_chart(분해, width="stretch")

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

        with st.expander("ℹ️ 자세히"):
            st.info(
                "**'작년보다 20% 늘었다' 만으로는 실력인지 장세인지 알 수 없습니다.**\\n\\n"
                "저축은 통제할 수 있고 시장수익은 통제할 수 없습니다. 시장이 좋았던 해에 "
                "저축을 게을리했다면 총증감은 커 보여도 실제로는 뒷걸음질일 수 있습니다. "
                "투자수익률은 기간 중간에 납입했다고 가정해 어림한 값(Modified Dietz)입니다.",
                icon="🔍")

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
                                f"{ui.억(연봉)} 기준으로 순자산이 **연평균 "
                                f"{ui.억(a['연간증가'])}** 씩 늘었습니다 "
                                f"(연봉의 {a['연봉대비']:.0f}%). "
                                f"현재 순자산은 연봉의 {a['연봉배수']:.1f}배입니다.\n\n"
                                "※ 저축률이 아닙니다. 시장 수익이 포함된 값이라 "
                                "연봉을 넘을 수도 있습니다.")
            except Exception:  # noqa: BLE001
                pass

    with st.expander("ℹ️ 자세히"):
        st.caption(
            "**비교가 왜곡되는 흔한 이유 네 가지** — ① 개인 자산만 넣고 가구 통계와 비교 "
            "② 예금·보증금·자동차를 빼먹음 ③ 부동산을 시세가 아닌 공시가격으로 넣음 "
            "④ 연령을 무시한 비교. 참고로 조사에서 가구주 50~59세 가구의 순자산이 "
            "5억 5,161만원으로 연령대 중 가장 높았습니다. 30대와 50대를 같은 잣대로 "
            "보시면 안 됩니다.")


st.divider()
저장_불러오기(저장키, 설정, "순자산", "_순자산_적용대기",
          도움말="기타 자산·부채, 배우자 자산, 순자산 기록이 함께 저장됩니다.")
