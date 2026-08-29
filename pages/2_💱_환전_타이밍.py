import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines.fx import (AVG_COLORS, CURRENCIES, MAIN_COLOR, 금액표시,  # noqa: E402
                        평균_계산, 타이밍_메시지, 환율_가져오기)

require_login(page_title="환전 타이밍", page_icon="💱", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("💱 환전 타이밍 대시보드")


@st.cache_data(ttl=3600, show_spinner=False)
def 데이터_조회(통화이름: str):
    return 환율_가져오기(CURRENCIES[통화이름])


# 통화 선택은 본문 맨 위에 둡니다.
#  ※ 사이드바에 두면 휴대폰에서 메뉴를 열어야 해서 바꾸기가 번거롭습니다.
짧은이름 = {
    "미국 달러 (USD)": "🇺🇸 달러",
    "일본 엔 (JPY)": "🇯🇵 엔",
    "유로 (EUR)": "🇪🇺 유로",
    "중국 위안 (CNY)": "🇨🇳 위안",
    "싱가포르 달러 (SGD)": "🇸🇬 싱달러",
}
선택 = st.radio("환전할 통화", list(CURRENCIES), horizontal=True,
              key="환율_통화", label_visibility="collapsed",
              format_func=lambda c: 짧은이름.get(c, c))

with st.sidebar:
    st.header("⚙️ 조회 설정")
    if st.button("🔄 최신 데이터 새로고침", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("종가 기준이라 은행의 실시간 고시 환율과는 차이가 날 수 있어요.")
    with st.expander("판단 기준 안내"):
        st.write(
            "최근 3년 종가로 3년·1년·6개월·3개월·1개월 평균을 계산합니다. "
            "현재가가 평균보다 낮은 구간이 많을수록 상대적으로 저렴한 것으로 표시합니다. "
            "참고용 지표이며 투자·환전 조언은 아닙니다."
        )

통화 = CURRENCIES[선택]
st.caption(f"{선택} · {통화['quote']} 기준")

try:
    with st.spinner("환율 데이터를 불러오는 중이에요..."):
        df, 출처, 기록 = 데이터_조회(선택)
except Exception as error:  # noqa: BLE001
    st.error("환율 데이터를 가져오지 못했어요. 인터넷 연결을 확인한 뒤 새로고침해 주세요.")
    st.code(str(error))
    st.stop()

현재가 = float(df["Close"].iloc[-1])
기준일 = df.index[-1].strftime("%Y년 %m월 %d일")
평균, 신뢰 = 평균_계산(df)
믿을만한 = {k: v for k, v in 평균.items() if 신뢰[k]}
저렴한수 = sum(현재가 < v for v in 믿을만한.values())
삼년 = df.loc[df.index >= df.index.max() - pd.DateOffset(years=3), "Close"]

st.metric(f"현재 환율 ({기준일} 종가)", 금액표시(현재가, 통화["unit"]))
if 믿을만한:
    st.markdown(f"#### 📊 {len(믿을만한)}개 구간 중 **{저렴한수}개** 평균보다 저렴해요")
    종류, 메시지 = 타이밍_메시지(round(저렴한수 * 5 / max(len(믿을만한), 1)))
    getattr(st, 종류)(메시지)
else:
    st.warning("과거 자료가 부족해서 평균과 비교할 수 없어요.", icon="⚠️")

if not all(신뢰.values()):
    부족 = [k for k, v in 신뢰.items() if not v]
    st.info(f"과거 자료가 짧아서 **{', '.join(부족)}** 은 계산할 수 없습니다. "
            "아래 '데이터 조회 경로'에서 어디서 받아왔는지 볼 수 있어요.", icon="ℹ️")

평균3년 = 평균["3년 평균"] if 신뢰["3년 평균"] else float(df["Close"].mean())
gauge = go.Figure(go.Indicator(
    mode="gauge+number",
    value=현재가,
    number={"suffix": 통화["unit"], "valueformat": ",.1f"},
    title={"text": "3년 범위 내 현재 위치 (검은 선 = 3년 평균)", "font": {"size": 13}},
    gauge={
        "axis": {"range": [float(삼년.min()), float(삼년.max())]},
        "bar": {"color": MAIN_COLOR},
        "steps": [
            {"range": [float(삼년.min()), 평균3년], "color": "#E3F1EC"},
            {"range": [평균3년, float(삼년.max())], "color": "#FBE9EC"},
        ],
        "threshold": {"line": {"color": "#22242A", "width": 3},
                      "thickness": 0.8, "value": 평균3년},
    },
))
gauge.update_layout(height=250, margin=dict(l=20, r=20, t=55, b=10))
ui.차트(gauge)

st.divider()
st.subheader("기간별 평균 대비 현재가")
항목 = list(평균.items())
for i in range(0, len(항목), 3):
    cols = st.columns(len(항목[i:i + 3]))
    for col, (라벨, 값) in zip(cols, 항목[i:i + 3]):
        if not 신뢰[라벨]:
            col.metric(라벨, "자료 부족", help="이 기간을 덮을 만큼 과거 자료가 없습니다")
            continue
        차이 = (현재가 - 값) / 값 * 100
        col.metric(라벨, 금액표시(값, 통화["unit"]), f"{차이:+.2f}%", delta_color="inverse")

st.divider()
st.subheader("환전 금액 계산")
c1, c2 = st.columns(2)
금액 = c1.number_input(f"환전할 금액 ({통화['quote']} 단위)", min_value=0.0, value=1000.0,
                    step=100.0, format="%.2f")
배수 = 금액 / (100 if 통화["scale"] == 100 else 1)
c2.metric("현재 환율로 필요한 원화", f"{배수 * 현재가:,.0f}원",
          (f"3년 평균 대비 {배수 * (현재가 - 평균3년):+,.0f}원" if 신뢰["3년 평균"]
           else f"전체 평균 대비 {배수 * (현재가 - 평균3년):+,.0f}원"),
          delta_color="inverse")

st.divider()
기간 = st.radio("추이 기간", ["6개월", "1년", "2년", "3년"], index=1, horizontal=True)
개월 = {"6개월": 6, "1년": 12, "2년": 24, "3년": 36}[기간]
최근 = df.loc[df.index >= df.index.max() - pd.DateOffset(months=개월)]

trend = go.Figure()
trend.add_trace(go.Scatter(x=최근.index, y=최근["Close"], mode="lines", name="종가",
                           line=dict(color=MAIN_COLOR, width=2)))
for 라벨, 값 in 믿을만한.items():
    trend.add_hline(y=값, line_dash="dot", line_color=AVG_COLORS[라벨],
                    annotation_text=라벨, annotation_position="right")
trend.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10),
                    yaxis_title=통화["chart_label"], hovermode="x unified")
ui.차트(trend)

st.caption(f"데이터 출처: {출처} · 1시간 단위로 캐시됩니다.")
if len(기록) > 1:
    with st.expander("데이터 조회 경로", expanded=not all(신뢰.values())):
        for 줄 in 기록:
            st.text(("  ✓ " if 줄.endswith("성공") else "  · ") + 줄)
        st.caption("첫 경로가 막히면 달러를 경유해 계산합니다. "
                   "예: 위안당 원화 = (달러당 원화) ÷ (달러당 위안)")
