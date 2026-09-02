"""
==========================================================================
환전 타이밍 대시보드
==========================================================================
[화면 구성]
 1. 지금 환율      — 어제·지난주 대비 등락을 함께 (단기 판단)
 2. 최근 흐름      — 1일 전 / 1주일 전 / 1주일 평균 + 30일 추세선
 3. 과거 평균 대비 — 3년·2년·1년·6·3·1개월 평균과 견주기 (장기 판단)
 4. 환전 금액 계산
 5. 추이 차트

단기와 장기를 일부러 나눠 놓았습니다. 성격이 다른 판단이라
한 덩어리로 두면 "평균보다 싸지만 어제보다 올랐다" 같은 상황을
읽어낼 수 없습니다.
==========================================================================
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
# fx 는 이름을 하나씩 가져오지 않고 모듈 전체로 받습니다.
#  ※ from engines.fx import 단기_요약 … 처럼 이름을 직접 가져오면,
#    engines/fx.py 가 예전 버전일 때 ImportError 가 로그인 화면보다
#    먼저 터집니다. 그러면 Streamlit 이 원인을 가리고
#    "error message is redacted" 만 보여주어서, 어떤 파일을 다시
#    올려야 하는지 화면에서 알 수 없습니다.
#    모듈로 받으면 import 자체는 성공하므로, 아래에서 한글로 안내합니다.
from engines import fx as FX  # noqa: E402

require_login(page_title="환전 타이밍", page_icon="💱", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

# 계산 파일이 예전 버전이면 여기서 멈추고 무엇을 올려야 하는지 알려줍니다.
#  (이 페이지가 쓰는 단기 비교 기능은 2026-09-02 판부터 있습니다)
if not hasattr(FX, "단기_요약"):
    st.error("**engines/fx.py 가 예전 버전입니다.**", icon="🔄")
    st.markdown(
        "이 페이지는 `engines/fx.py` 의 단기 비교 기능(1일 전·1주일 전)을 씁니다. "
        "지금 올라와 있는 파일에는 그 기능이 없습니다.\n\n"
        "1. GitHub 저장소의 **engines 폴더로 들어가서** `fx.py` 를 다시 올리세요.\n"
        "   (저장소 첫 화면에 올리면 `engines/fx.py` 가 아니라 새 파일이 생깁니다)\n"
        "2. Streamlit Cloud 오른쪽 아래 **Manage app → Reboot app** 을 누르세요.\n"
        "   공용 파일은 앱을 다시 시작해야 바뀝니다.")
    st.stop()

ui.페이지_메뉴(__file__)
st.title("💱 환전 타이밍")


@st.cache_data(ttl=3600, show_spinner=False)
def 데이터_조회(통화이름: str):
    return FX.환율_가져오기(FX.CURRENCIES[통화이름])


# 통화 선택은 본문 맨 위에 둡니다.
#  ※ 사이드바에 두면 휴대폰에서 메뉴를 열어야 해서 바꾸기가 번거롭습니다.
짧은이름 = {
    "미국 달러 (USD)": "🇺🇸 달러",
    "일본 엔 (JPY)": "🇯🇵 엔",
    "유로 (EUR)": "🇪🇺 유로",
    "중국 위안 (CNY)": "🇨🇳 위안",
    "싱가포르 달러 (SGD)": "🇸🇬 싱달러",
}
선택 = ui.선택줄("환전할 통화", list(FX.CURRENCIES), key="환율_통화",
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
            "**단기** — 어제·지난주 종가와 지금을 견줍니다. 며칠 안에 환전할 때 "
            "보시면 됩니다.\n\n"
            "**장기** — 최근 3년 종가로 3년·2년·1년·6개월·3개월·1개월 평균을 "
            "계산합니다. 현재가가 평균보다 낮은 구간이 많을수록 상대적으로 "
            "저렴한 것으로 표시합니다.\n\n"
            "참고용 지표이며 투자·환전 조언은 아닙니다."
        )

통화 = FX.CURRENCIES[선택]

try:
    with st.spinner("환율 데이터를 불러오는 중이에요..."):
        df, 출처, 기록 = 데이터_조회(선택)
except Exception as error:  # noqa: BLE001
    st.error("환율 데이터를 가져오지 못했어요. 인터넷 연결을 확인한 뒤 새로고침해 주세요.")
    st.code(str(error))
    st.stop()

현재가 = float(df["Close"].iloc[-1])
기준일 = df.index[-1].strftime("%Y년 %m월 %d일")
평균, 신뢰 = FX.평균_계산(df)
믿을만한 = {k: v for k, v in 평균.items() if 신뢰[k]}
저렴한수 = sum(현재가 < v for v in 믿을만한.values())
삼년 = df.loc[df.index >= df.index.max() - pd.DateOffset(years=3), "Close"]
단기 = FX.단기_요약(df)
단기표 = {r["라벨"]: r for r in 단기}


# ==========================================================================
# 1. 지금 환율
# ==========================================================================
def _뱃지(라벨: str, 이름: str) -> str:
    """어제/지난주 등락을 알약 모양으로. 값이 없으면 빈 문자열."""
    r = 단기표.get(라벨)
    if not r or not r.get("신뢰"):
        return ""
    v = r["변동률"]
    화살 = "▲" if v > 0 else ("▼" if v < 0 else "―")
    # 환율이 오르면 원화가 더 든다 = 나쁨. 부호와 색을 뒤집습니다.
    종류 = "나쁨" if v > 0.05 else ("좋음" if v < -0.05 else "중립")
    return ui.뱃지(f"{이름} {화살} {abs(v):.2f}%", 종류)


ui.헤드라인(
    f"{짧은이름.get(선택, 선택)} · {통화['quote']} 기준 ({기준일} 종가)",
    FX.금액표시(현재가, 통화["unit"]),
    뱃지들=[b for b in (_뱃지("1일 전", "어제 대비"),
                     _뱃지("1주일 전", "지난주 대비")) if b])

종류, 메시지 = FX.단기_메시지(단기)
getattr(st, 종류)(메시지)


# ==========================================================================
# 2. 최근 흐름 — 1일 전 · 1주일 전 · 1주일 평균
# ==========================================================================
ui.섹션("최근 흐름", "며칠 사이 움직임입니다. 지금 환전할지 이번 주를 더 볼지 "
                "정할 때 보세요.", 라벨="단기")

칸들 = st.columns(3)
for 칸, 라벨 in zip(칸들, ["1일 전", "1주일 전", "1주일 평균"]):
    r = 단기표.get(라벨)
    if not r:
        칸.metric(라벨, "-")
        continue
    if not r.get("신뢰"):
        칸.metric(라벨, "자료 부족", help=r.get("설명", ""))
        continue
    칸.metric(라벨, FX.금액표시(r["값"], 통화["unit"]),
             f"{r['변동률']:+.2f}%", delta_color="inverse",
             help=f"{r['설명']} · 차이 {r['차이']:+,.2f}{통화['unit']}")

st.caption("위 %는 **그때보다 지금 얼마나 비싼지**입니다. "
           "＋면 원화가 더 들고(빨강), −면 덜 듭니다(초록). "
           "주말·공휴일에는 종가가 없어서 그 직전 영업일 값을 씁니다.")

한달 = df.loc[df.index >= df.index.max() - pd.DateOffset(days=30), "Close"]
if len(한달) >= 3:
    ui.미니차트(list(zip(한달.index, 한달.values)), 색이름="청록", 높이=100,
             채우기=False, key="fx_mini",
             hover="%{x|%m월 %d일}<br>%{y:,.2f}" + 통화["unit"] + "<extra></extra>")
    st.caption(f"최근 30일 흐름 ({한달.index[0]:%m/%d}~{한달.index[-1]:%m/%d})")


# ==========================================================================
# 3. 과거 평균 대비
# ==========================================================================
st.divider()
ui.섹션("과거 평균 대비", "몇 달~몇 년 흐름에서 지금이 어디쯤인지 봅니다.",
      라벨="장기")

if 믿을만한:
    st.markdown(f"**{len(믿을만한)}개 구간 중 {저렴한수}개** 평균보다 저렴해요")
    종류, 메시지 = FX.타이밍_메시지(round(저렴한수 * 5 / max(len(믿을만한), 1)))
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
    number={"suffix": 통화["unit"], "valueformat": ",.1f",
            "font": {"size": 30}},
    title={"text": "3년 범위 내 현재 위치 (회색 선 = 3년 평균)", "font": {"size": 13}},
    gauge={
        "axis": {"range": [float(삼년.min()), float(삼년.max())],
                 "tickwidth": 1, "tickcolor": "rgba(128,128,128,.5)"},
        "bar": {"color": FX.MAIN_COLOR, "thickness": 0.7},
        "bgcolor": "rgba(0,0,0,0)",
        "borderwidth": 0,
        "steps": [
            {"range": [float(삼년.min()), 평균3년], "color": "rgba(24,165,122,.16)"},
            {"range": [평균3년, float(삼년.max())], "color": "rgba(192,57,43,.14)"},
        ],
        "threshold": {"line": {"color": "rgba(128,128,128,.9)", "width": 3},
                      "thickness": 0.8, "value": 평균3년},
    },
))
gauge.update_layout(height=240, margin=dict(l=20, r=20, t=55, b=6),
                    paper_bgcolor="rgba(0,0,0,0)", font=dict(size=12))
ui.차트(gauge, 테마=False)
st.caption("왼쪽 초록 구간은 3년 평균보다 싼 쪽, 오른쪽 붉은 구간은 비싼 쪽입니다.")

항목 = list(평균.items())
for i in range(0, len(항목), 3):
    cols = st.columns(len(항목[i:i + 3]))
    for col, (라벨, 값) in zip(cols, 항목[i:i + 3]):
        if not 신뢰[라벨]:
            col.metric(라벨, "자료 부족", help="이 기간을 덮을 만큼 과거 자료가 없습니다")
            continue
        차이 = (현재가 - 값) / 값 * 100
        col.metric(라벨, FX.금액표시(값, 통화["unit"]), f"{차이:+.2f}%",
                   delta_color="inverse")


# ==========================================================================
# 4. 환전 금액 계산
# ==========================================================================
st.divider()
ui.섹션("환전 금액 계산", f"{통화['quote']} 단위로 넣으면 필요한 원화를 계산합니다.")

c1, c2 = st.columns(2)
금액 = c1.number_input(f"환전할 금액 ({통화['quote']} 단위)", min_value=0.0,
                    value=1000.0, step=100.0, format="%.2f")
배수 = 금액 / (100 if 통화["scale"] == 100 else 1)
c2.metric("현재 환율로 필요한 원화", f"{배수 * 현재가:,.0f}원",
          (f"3년 평균 대비 {배수 * (현재가 - 평균3년):+,.0f}원" if 신뢰["3년 평균"]
           else f"전체 평균 대비 {배수 * (현재가 - 평균3년):+,.0f}원"),
          delta_color="inverse")

주간 = 단기표.get("1주일 전")
if 금액 > 0 and 주간 and 주간.get("신뢰"):
    # 부호만 던지면 어느 쪽이 유리한지 읽기 어렵습니다. 말로 풀어 씁니다.
    차 = 배수 * 주간["차이"]
    if abs(차) < 1:
        st.caption("지난주 환율이었어도 원화 금액은 거의 같았습니다.")
    else:
        st.caption(f"지난주 환율이었다면 **{abs(차):,.0f}원** "
                   + ("더 들었습니다." if 차 < 0 else "덜 들었습니다."))


# ==========================================================================
# 5. 추이 차트
# ==========================================================================
st.divider()
기간 = ui.선택줄("추이 기간", ["1개월", "6개월", "1년", "2년", "3년"],
              key="환율_추이기간", 기본=2)
개월 = {"1개월": 1, "6개월": 6, "1년": 12, "2년": 24, "3년": 36}[기간]
최근 = df.loc[df.index >= df.index.max() - pd.DateOffset(months=개월)]

trend = go.Figure()
trend.add_trace(go.Scatter(x=최근.index, y=최근["Close"], mode="lines", name="종가",
                           line=dict(color=FX.MAIN_COLOR, width=2)))

# 1개월 화면에서는 몇 년 평균선이 화면 밖으로 나가 쓸모가 없습니다.
# 대신 단기 기준선(1주일 평균)을 깔아 줍니다.
기준선 = []
if 개월 <= 1:
    주평균 = 단기표.get("1주일 평균")
    if 주평균 and 주평균.get("신뢰"):
        기준선.append(("1주일 평균", 주평균["값"]))
    if 신뢰.get("1개월 평균"):
        기준선.append(("1개월 평균", 평균["1개월 평균"]))
else:
    기준선 = list(믿을만한.items())

# 평균선 이름을 선 끝에 적으면, 값이 비슷한 평균끼리(예: 3년 1,401원과
# 1개월 1,404원) 글자가 겹쳐서 못 읽습니다. 그래서 이름은 위쪽 범례에
# 몰아두고, 선에는 색만 남겼습니다. 색이 곧 이름입니다.
for 라벨, 값 in 기준선:
    trend.add_hline(y=값, line_dash="dot", line_color=FX.AVG_COLORS[라벨])
    trend.add_trace(go.Scatter(
        x=[최근.index[-1]], y=[값], mode="lines",
        line=dict(color=FX.AVG_COLORS[라벨], width=2, dash="dot"),
        name=f"{라벨} {FX.금액표시(값, 통화['unit'])}",
        hoverinfo="skip", showlegend=True))

trend.update_layout(height=390, margin=dict(l=10, r=14, t=64, b=10),
                    yaxis_title=통화["chart_label"], hovermode="x unified",
                    legend=dict(orientation="h", y=1.16, x=0,
                                yanchor="bottom", font=dict(size=10)))
ui.차트(trend)

st.caption(f"데이터 출처: {출처} · 1시간 단위로 캐시됩니다.")
if len(기록) > 1:
    with st.expander("데이터 조회 경로", expanded=not all(신뢰.values())):
        for 줄 in 기록:
            st.text(("  ✓ " if 줄.endswith("성공") else "  · ") + 줄)
        st.caption("첫 경로가 막히면 달러를 경유해 계산합니다. "
                   "예: 위안당 원화 = (달러당 원화) ÷ (달러당 위안)")
