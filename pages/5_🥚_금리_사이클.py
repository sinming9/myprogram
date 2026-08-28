import os
import sys
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import 불러온것_적용, 저장_불러오기  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import egg_cycle as EC  # noqa: E402
from engines import fedwatch as FW  # noqa: E402
from engines import yields as YD  # noqa: E402

require_login(page_title="금리 사이클", page_icon="🥚", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("🥚 달걀 모형 금리 사이클")
st.caption("코스톨라니 달걀 · 기준금리 위치로 보는 자산 배분 국면")

저장키 = "egg_cycle"
기본설정 = {"country": "KR", "cycle_low": None, "cycle_high": None,
          "manual_rate": None, "lookback_years": 3, "추가이력": [],
          "인상성격": "모름", "수동확률": None, "수동방향": "동결"}

if "달걀_설정" not in st.session_state:
    불러온 = storage.불러오기(저장키, {}) or {}
    설정 = dict(기본설정)
    설정.update({k: v for k, v in 불러온.items() if k in 기본설정})
    st.session_state["달걀_설정"] = 설정
    st.session_state.setdefault("달걀_표버전", 0)
st.session_state.setdefault("달걀_표버전", 0)


def _설정_적용(데이터):
    기본 = dict(기본설정)
    기본.update({k: v for k, v in (데이터 or {}).items() if k in 기본설정})
    st.session_state["달걀_설정"] = 기본
    st.session_state["달걀_표버전"] += 1


불러온것_적용("_달걀_적용대기", _설정_적용)
설정 = st.session_state["달걀_설정"]

storage.임시서버_안내()

# ==========================================================================
# 입력
# ==========================================================================
나라 = st.radio("대상", ["KR", "US"], horizontal=True, key="달걀_나라",
              format_func=lambda c: {"KR": "🇰🇷 한국 (한국은행 기준금리)",
                                     "US": "🇺🇸 미국 (연방기금금리 상단)"}[c],
              index=["KR", "US"].index(설정.get("country", "KR")))
설정["country"] = 나라

api_key = None
for 이름 in (("ECOS_API_KEY", "ecos_api_key") if 나라 == "KR"
            else ("FRED_API_KEY", "fred_api_key")):
    try:
        api_key = st.secrets[이름]
        break
    except Exception:  # noqa: BLE001
        api_key = os.environ.get(이름.upper())
        if api_key:
            break


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def 이력_조회(나라, 키있음, 키, 추가):
    return EC.이력_불러오기(나라, 키 if 키있음 else None, 추가)


추가이력 = [(d, v) for d, v in 설정.get("추가이력", [])]
with st.spinner("금리 이력을 불러오는 중이에요..."):
    이력, 출처, 조회오류 = 이력_조회(나라, bool(api_key), api_key or "", tuple(추가이력))

if 조회오류:
    st.warning(f"자동 조회에 실패해서 내장 기본값을 씁니다. ({조회오류})", icon="⚠️")

수동금리 = 설정.get("manual_rate")
if 수동금리 is not None:
    이력 = EC.RateHistory(list(이력.points) + [(date.today(), float(수동금리))]).sort()
    출처 = "직접 입력"

설정정보 = EC.CycleConfig(
    country=나라,
    cycle_low=설정.get("cycle_low"),
    cycle_high=설정.get("cycle_high"),
    lookback_years=int(설정.get("lookback_years", 3)),
)
상태 = EC.compute_state(이력, 설정정보, 출처)

# ==========================================================================
# 요약
# ==========================================================================
화살표 = {"인상": "▲", "인하": "▼", "동결": "―"}[상태.direction]
변경문구 = (f"{상태.last_change_date:%Y-%m-%d} · {상태.last_change_bp:+.0f}bp"
        if 상태.last_change_date else "이력 없음")

ui.카드_줄([
    ("현재 기준금리", f"{상태.rate:.2f}%", f"{화살표} {상태.direction} · {상태.as_of:%Y-%m-%d} 기준"),
    ("사이클 위치", f"{상태.r * 100:.0f}%", f"{상태.cycle_low:.2f}% ~ {상태.cycle_high:.2f}% 밴드"),
    ("현재 국면", 상태.phase.name, 상태.phase.regime),
    ("최근 변경", 변경문구,
     f"{상태.days_since_change}일 경과" + (" · 장기 동결" if 상태.plateau else "")
     if 상태.days_since_change is not None else ""),
], 열수=2)

강조 = {"호황기": "info", "불황기": "warning", "전환점": "success"}[상태.phase.regime]
getattr(st, 강조)(f"**이론상 포지션 — {상태.phase.action}**\n\n{상태.phase.note}")

# ==========================================================================

# ==========================================================================
# 탭으로 묶기 (탭 3개 — 휴대폰에서 한 줄에 들어갑니다)
#  다시 그리는 버튼은 탭 밖 아래에 둡니다. rerun 이 나면 첫 탭으로 돌아가서요.
# ==========================================================================
# ==========================================================================
# 다음 회의 · 시장 확률 계산
#  ※ 계산은 탭보다 먼저 합니다. 달걀 차트(탭국면)가 이 결과를 쓰는데,
#    Streamlit 은 탭과 무관하게 위에서 아래로 실행하기 때문입니다.
# ==========================================================================
# 다음 회의 · 시장이 보는 확률
# ==========================================================================
st.subheader("다음 회의")

오늘 = date.today()
다음금통위 = FW.다음_회의(FW.금통위_일정, 오늘)
다음FOMC = FW.다음_회의(FW.FOMC_일정, 오늘)

m1, m2 = st.columns(2)
m1.metric("🇰🇷 금통위",
          다음금통위.strftime("%m월 %d일") if 다음금통위 else "일정 없음",
          f"D-{(다음금통위 - 오늘).days}" if 다음금통위 else None, delta_color="off")
m2.metric("🇺🇸 FOMC",
          다음FOMC.strftime("%m월 %d일") if 다음FOMC else "일정 없음",
          f"D-{(다음FOMC - 오늘).days}" if 다음FOMC else None, delta_color="off")


@st.cache_data(ttl=3600, show_spinner=False)
def 미국확률_조회(fred키, 목표상단):
    return FW.미국_전망(fred_key=fred키, 목표상단=목표상단)


def _미국_목표상단():
    """FRED 키가 없을 때 실효금리를 추정하려면 현재 목표범위 상단이 필요합니다."""
    if 나라 == "US":
        return float(상태.rate)
    미국이력, _출처, _오류 = EC.이력_불러오기("US", None, ())
    return float(미국이력.latest[1]) if 미국이력.points else None


fred키 = None
for 이름 in ("FRED_API_KEY", "fred_api_key"):
    try:
        fred키 = st.secrets[이름]
        break
    except Exception:  # noqa: BLE001
        fred키 = os.environ.get(이름.upper())
        if fred키:
            break

예측 = None
with st.spinner("연방기금 선물에서 확률을 계산하는 중이에요..."):
    자동, 조회기록 = 미국확률_조회(fred키, _미국_목표상단())


# 한 줄 요약
_조각 = [f"{상태.rate:.2f}% {상태.direction}", 상태.phase.name,
       f"사이클 {상태.r * 100:.0f}%"]
if 다음FOMC:
    _조각.append(f"FOMC D-{(다음FOMC - date.today()).days}")
if 자동:
    _조각.append(f"{자동['방향']} {자동['확률'] * 100:.0f}%")
st.markdown(
    f"### {상태.phase.regime} "
    f"<span style='font-size:.62em;opacity:.75'>"
    + " · ".join(_조각[1:]) + "</span>", unsafe_allow_html=True)

탭국면, 탭금리, 탭일정 = st.tabs(["국면", "금리", "일정"])

with 탭국면:
    # 달걀 차트 (plotly)
    # ==========================================================================
    호황색 = "rgba(230, 126, 34, 0.16)"
    불황색 = "rgba(52, 120, 216, 0.16)"
    윤곽색 = "rgba(140, 140, 140, 0.85)"
    현재색 = "#D62828"

    fig = go.Figure()

    # 좌(호황) / 우(불황) 반쪽 채우기
    왼x, 왼y = EC.egg_outline(90, 270, 181)
    fig.add_trace(go.Scatter(x=왼x, y=왼y, fill="toself", fillcolor=호황색,
                             line=dict(width=0), hoverinfo="skip", showlegend=False))
    오른x, 오른y = EC.egg_outline(-90, 90, 181)
    fig.add_trace(go.Scatter(x=오른x, y=오른y, fill="toself", fillcolor=불황색,
                             line=dict(width=0), hoverinfo="skip", showlegend=False))

    # 윤곽선
    xs, ys = EC.egg_outline()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                             line=dict(color=윤곽색, width=2),
                             hoverinfo="skip", showlegend=False))

    # 기준점 A~F
    점x, 점y, 점글, 점위치, 점설명 = [], [], [], [], []
    for 코드, r, side, 라벨 in EC.MARKERS:
        각 = EC.marker_angle(r, side)
        x, y = EC.point_at(각)
        점x.append(x)
        점y.append(y)
        점글.append(f"<b>{코드}</b>")
        점설명.append(f"{코드} · {라벨}")
        점위치.append("top center" if y > 1 else "bottom center" if y < -1
                    else ("middle left" if x < 0 else "middle right"))

    fig.add_trace(go.Scatter(
        x=점x, y=점y, mode="markers+text", text=점글, textposition=점위치,
        textfont=dict(size=13),
        marker=dict(size=11, color="rgba(120,120,120,0.9)",
                    line=dict(color="rgba(255,255,255,0.8)", width=1.5)),
        customdata=점설명, hovertemplate="%{customdata}<extra></extra>",
        showlegend=False))

    # 기준점 설명 라벨 (바깥쪽)
    for 코드, r, side, 라벨 in EC.MARKERS:
        각 = EC.marker_angle(r, side)
        x, y = EC.point_at(각)
        fig.add_annotation(x=x * 1.9, y=y * 1.12, text=라벨, showarrow=False,
                           font=dict(size=10), opacity=0.75,
                           xanchor="center" if abs(x) < 0.1 else ("right" if x < 0 else "left"))

    # 현재 위치
    현x, 현y = EC.point_at(상태.angle_deg)
    fig.add_trace(go.Scatter(
        x=[현x], y=[현y], mode="markers+text",
        text=[f"<b>{상태.rate:.2f}%</b>"], textposition="middle center",
        textfont=dict(size=11, color="white"),
        marker=dict(size=34, color=현재색, line=dict(color="white", width=2)),
        hovertemplate=(f"현재 {상태.rate:.2f}%<br>{상태.phase.name}"
                       f"<br>사이클 {상태.r * 100:.0f}%<extra></extra>"),
        showlegend=False))

    # 예상 이동 위치 (다음 회의 결과가 반영되면 어디로 가는지)
    if 예측 and 예측.get("방향") in ("인상", "인하") and 예측.get("확률", 0) >= 0.5:
        폭 = 0.25 / max(상태.cycle_high - 상태.cycle_low, 0.01)
        새r = min(max(상태.r + (폭 if 예측["방향"] == "인상" else -폭), 0.0), 1.0)
        새side = "up" if 예측["방향"] == "인상" else "down"
        예상각 = EC.angle_for(새r, 새side)
        예상x, 예상y = EC.point_at(예상각)
        fig.add_trace(go.Scatter(
            x=[현x, 예상x], y=[현y, 예상y], mode="lines",
            line=dict(color=현재색, width=2, dash="dot"),
            hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(
            x=[예상x], y=[예상y], mode="markers",
            marker=dict(size=20, color="rgba(0,0,0,0)", line=dict(color=현재색, width=2)),
            hovertemplate=(f"{예측['방향']} 시 예상 위치<br>"
                           f"확률 {예측['확률'] * 100:.0f}%<extra></extra>"),
            showlegend=False))

    # 가운데 안내
    fig.add_annotation(x=0, y=0.18, text=f"<b>{상태.phase.name}</b>",
                       showarrow=False, font=dict(size=15))
    fig.add_annotation(x=0, y=-0.05, text=상태.phase.regime,
                       showarrow=False, font=dict(size=12), opacity=0.8)
    fig.add_annotation(x=-0.62, y=1.72, text="◀ 금리 상승 · 호황기",
                       showarrow=False, font=dict(size=11), opacity=0.7)
    fig.add_annotation(x=0.62, y=1.72, text="금리 하락 · 불황기 ▶",
                       showarrow=False, font=dict(size=11), opacity=0.7)

    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(visible=False, range=[-2.6, 2.6], fixedrange=True),
        yaxis=dict(visible=False, range=[-1.85, 1.9], fixedrange=True,
                   scaleanchor="x", scaleratio=1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")
    안내 = f"데이터 출처: {출처} · 왼쪽 = 금리 상승(호황기), 오른쪽 = 금리 하락(불황기)"
    if 예측 and 예측.get("방향") in ("인상", "인하") and 예측.get("확률", 0) >= 0.5:
        안내 += f" · 점선 = 다음 회의에서 {예측['방향']} 시 예상 위치"
    st.caption(안내)

    with st.expander("📖 6개 국면 전체 보기"):
        순서 = ["D", "D-E", "E", "E-F", "F", "F-A", "A", "A-B", "B", "B-C", "C", "C-D"]
        표 = pd.DataFrame([{
            "지금": "◀" if EC.PHASES[k].code == 상태.phase.code else "",
            "국면": EC.PHASES[k].name,
            "구분": EC.PHASES[k].regime,
            "이론상 포지션": EC.PHASES[k].action,
            "해설": EC.PHASES[k].note,
        } for k in 순서])
        st.dataframe(표, width="stretch", hide_index=True, height=460)
        st.caption(
            "달걀 모형은 금리 사이클과 자산 가격의 일반적 관계를 설명하는 이론적 틀입니다. "
            "실제 시장은 이론대로 움직이지 않는 경우가 많고, 이 화면은 참고용 지표일 뿐 "
            "투자 권유가 아닙니다."
        )

    # ==========================================================================

with 탭금리:
    # 금리 추이
    # ==========================================================================
    st.subheader("기준금리 추이")

    날짜, 값 = 이력.계단_시계열()
    추이 = go.Figure()
    추이.add_trace(go.Scatter(x=날짜, y=값, mode="lines+markers", line_shape="hv",
                            line=dict(color="#2B6ED5", width=2), name="기준금리"))
    추이.add_hline(y=상태.cycle_high, line_dash="dot", line_color="rgba(214,40,40,.7)",
                 annotation_text=f"사이클 고점 {상태.cycle_high:.2f}%", annotation_position="right")
    추이.add_hline(y=상태.cycle_low, line_dash="dot", line_color="rgba(40,140,90,.7)",
                 annotation_text=f"사이클 저점 {상태.cycle_low:.2f}%", annotation_position="right")
    추이.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="%", hovermode="x unified")
    st.plotly_chart(추이, width="stretch")

    st.subheader("🇺🇸 국채 수익률 곡선")
    st.caption("정책금리는 중앙은행이 정하지만 **국채금리는 시장이 정합니다.** "
               "둘이 따로 움직일 때가 중요한 국면입니다.")


    @st.cache_data(ttl=6 * 3600, show_spinner=False)
    def 곡선_가져오기(키있음, 키):
        return YD.곡선_조회(키 if 키있음 else None)


    fred키 = None
    for _이름 in ("FRED_API_KEY", "fred_api_key"):
        try:
            fred키 = st.secrets[_이름]
            break
        except Exception:  # noqa: BLE001
            fred키 = os.environ.get(_이름.upper())
            if fred키:
                break

    with st.spinner("국채 수익률을 불러오는 중이에요..."):
        곡선자료, 곡선출처, 곡선기록 = 곡선_가져오기(bool(fred키), fred키 or "")

    수동곡선 = 설정.get("수동곡선") or {}
    if 곡선자료:
        현재값 = YD.최근값(곡선자료)
        기준일표시 = max(점들[-1][0] for 점들 in 곡선자료.values()).isoformat()
    else:
        현재값 = {k: float(수동곡선.get(k) or YD.기본값[k])
                for k in YD.기본_만기}
        기준일표시 = 수동곡선.get("기준일") or YD.기본값["기준일"]

    ui.카드_줄([
        (f"{k} 국채", f"{현재값[k]:.2f}%",
         (f"{YD.변화(곡선자료, k, 30):+.0f}bp (30일)"
          if 곡선자료 and YD.변화(곡선자료, k, 30) is not None else "직접 입력"))
        for k in YD.기본_만기 if k in 현재값
    ] + [("기준금리 대비", f"{현재값.get('30년', 0) - 상태.rate:+.2f}%p",
          "30년물 − 정책금리")], 열수=2)
    st.caption(f"기준일 {기준일표시} · 출처 {곡선출처}")

    # ---- 스프레드 ----
    스프 = YD.스프레드(현재값)
    if 스프:
        칸 = st.columns(len(스프))
        for col, (이름, d) in zip(칸, 스프.items()):
            col.metric(이름, f"{d['값']:+.2f}%p",
                       "역전" if d["역전"] else None,
                       delta_color="inverse" if d["역전"] else "off")
        역전목록 = [k for k, d in 스프.items() if d["역전"]]
        if 역전목록:
            st.error(f"**{', '.join(역전목록)} 역전** — 단기금리가 장기금리보다 높습니다. "
                     "과거 침체를 앞두고 자주 나타난 모양이라 경기 신호로 읽히지만, "
                     "역전 뒤 실제 침체까지의 시차는 매번 크게 달랐습니다.", icon="⚠️")

    # ---- 곡선 모양 ----
    if 곡선자료:
        모양 = YD.곡선_모양(곡선자료, "2년", "30년", 30)
        if 모양["유형"] != "판단 보류":
            색 = {"베어 스티프닝": "warning", "베어 플래트닝": "warning",
                 "불 스티프닝": "info", "불 플래트닝": "info"}[모양["유형"]]
            getattr(st, 색)(
                f"**최근 30일: {모양['유형']}** — {모양['설명']}\n\n"
                f"2년 {모양['단기변화']:+.0f}bp · 30년 {모양['장기변화']:+.0f}bp "
                f"(차이 {모양['스프레드변화']:+.0f}bp)\n\n"
                f"**통상 해석** — {모양['통상해석']}\n\n"
                f"**영향** — {모양['영향']}")

        곡선그림 = go.Figure()
        색표 = {"2년": "#18A57A", "10년": "#2B6ED5", "30년": "#C0392B"}
        for 이름, 점들 in 곡선자료.items():
            곡선그림.add_trace(go.Scatter(
                x=[d for d, _ in 점들], y=[v for _, v in 점들], mode="lines",
                name=f"{이름} 국채", line=dict(color=색표.get(이름), width=2),
                hovertemplate=f"{이름} %{{y:.2f}}%<extra></extra>"))
        곡선그림.add_hline(y=상태.rate, line_dash="dot",
                       line_color="rgba(140,140,140,.8)")
        곡선그림.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                           yaxis_title="%", hovermode="x unified",
                           legend=dict(orientation="h", y=1.15))
        st.plotly_chart(곡선그림, width="stretch")
        st.caption(f"회색 점선 = 현재 기준금리 {상태.rate:.2f}%")

    # ---- 정책금리 대비 · 주담대 ----
    if "30년" in 현재값:
        p = YD.정책금리_대비(현재값["30년"], 상태.rate)
        st.caption(f"📌 {p['상태']} (30년물 − 정책금리 = {p['차이']:+.2f}%p)")
    if "10년" in 현재값:
        st.caption(f"🏠 {YD.주담대_영향(현재값['10년'])}")

    with st.expander("⚙️ 국채 수익률 직접 입력 / 조회 내역"):
        for 줄 in 곡선기록:
            st.text("  " + 줄)
        if not fred키:
            st.caption("FRED 키를 넣으면 자동으로 받아옵니다. "
                       "🔑 자동 조회 설정에서 `fred_api_key` 를 넣으세요. "
                       "없으면 아래에 직접 넣으시면 됩니다.")
        y1, y2, y3 = st.columns(3)
        입력 = {}
        for col, 이름 in zip((y1, y2, y3), YD.기본_만기):
            입력[이름] = col.number_input(
                f"{이름} (%)", min_value=0.0, max_value=25.0, step=0.01,
                value=float(수동곡선.get(이름) or YD.기본값[이름]),
                format="%.2f", key=f"곡선_{이름}")
        기준입력 = st.text_input("기준일", value=수동곡선.get("기준일") or YD.기본값["기준일"],
                              key="곡선_기준일")
        if st.button("직접 입력한 값 쓰기", width="stretch"):
            설정["수동곡선"] = {**입력, "기준일": 기준입력}
            st.cache_data.clear()
            st.rerun()
        st.caption("내장 기본값은 2026년 8월 18일 보도 기준입니다 "
                   "(30년 5.31% · 10년 4.72%). 시간이 지나면 직접 갱신하시거나 "
                   "FRED 키를 넣으세요.")

    with st.expander("ℹ️ 모형의 전제"):
        st.warning(
            "**곡선 모양의 해석은 '통상' 그렇다는 것이지 법칙이 아닙니다.** "
            "특히 지금처럼 재정적자·국채 공급 같은 **수급 요인**이 장기금리를 밀어 올리는 "
            "국면에서는 교과서적 해석이 잘 안 맞습니다. 물가가 둔화되는데도 장기금리가 "
            "오를 수 있고, 중앙은행이 정책금리를 내려도 장기금리는 안 내려갈 수 있습니다.\n\n"
            "달걀 모형은 **정책금리**만 봅니다. 장기금리가 따로 움직이는 국면에서는 "
            "위 달걀 위치와 여기 곡선을 함께 보셔야 합니다.", icon="⚠️")

    # ==========================================================================

with 탭일정:
    if 자동:
        예측 = 자동
        색 = {"인상": "warning", "인하": "info", "동결": "success"}[자동["방향"]]
        getattr(st, 색)(
            f"**시장은 {자동['회의일']:%m월 %d일} FOMC 에서 "
            f"{자동['방향']} 확률을 {자동['확률'] * 100:.1f}% 로 보고 있습니다** "
            f"(동결 {자동['동결확률'] * 100:.1f}%)\n\n"
            f"현재 실효금리 {자동['현재금리']:.2f}% → 회의 후 {자동['회의후금리']:.2f}% "
            f"({자동['변화폭bp']:+.1f}bp) · 30일 연방기금 선물 {자동['티커']} 기준"
        )
    else:
        st.warning("선물 가격을 자동으로 받지 못했습니다. 아래에서 직접 넣어주세요.", icon="⚠️")

    with st.expander("🎯 시장 확률 직접 입력 / 계산 내역", expanded=not 자동):
        for 줄 in 조회기록:
            st.text("  " + 줄)
        with st.expander("ℹ️ 확률은 어떻게 계산하나"):
            st.caption(
                "CME FedWatch 는 무료 API 가 없어서, 그 도구가 쓰는 원본 데이터인 "
                "30일 연방기금 선물(ZQ)을 직접 받아 같은 공식으로 계산합니다.\n\n"
                "계약가 → 그 달 평균금리(100 − 가격) → 회의 전후 일수로 가중평균을 풀어 "
                "회의 후 금리를 역산 → 0.25%p 로 나눈 값이 확률입니다.\n\n"
                "다음 회의 한 번만 계산하므로 CME 값과 소수점 단위 차이가 날 수 있고, "
                "그 다음 회의부터는 차이가 커집니다. 정확한 값은 CME 에서 확인하세요."
            )
        st.link_button("CME FedWatch 열기",
                       "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
                       width="stretch")

        st.markdown("##### 직접 입력")
        d1, d2 = st.columns(2)
        수동방향 = d1.selectbox("예상 방향", ["동결", "인상", "인하"],
                            index=["동결", "인상", "인하"].index(설정.get("수동방향", "동결")),
                            key="달걀_수동방향")
        수동확률 = d2.slider("그 방향의 확률(%)", 0, 100,
                         int(설정.get("수동확률") or 0), step=5, key="달걀_수동확률")
        if st.checkbox("자동 계산 대신 위 값을 쓰기", key="달걀_수동사용",
                       value=설정.get("수동확률") is not None):
            예측 = {"방향": 수동방향, "확률": 수동확률 / 100,
                  "회의일": 다음FOMC, "출처": "직접 입력"}
            설정["수동방향"] = 수동방향
            설정["수동확률"] = 수동확률
        else:
            설정["수동확률"] = None

    # ---- 이번 인상이 어떤 성격인가 ----
    성격목록 = ["모름", "수요견인 (경기 확장)", "비용충격 (유가·환율 등)"]
    성격 = st.radio("이번 금리 국면의 성격", 성격목록, horizontal=True,
                  index=성격목록.index(설정.get("인상성격", "모름"))
                  if 설정.get("인상성격") in 성격목록 else 0,
                  key="달걀_성격")
    설정["인상성격"] = 성격
    if 성격.startswith("비용충격"):
        with st.expander("ℹ️ 모형의 전제"):
            st.warning(
                "**달걀 모형의 전제와 다른 국면입니다.**\n\n"
                "달걀 모형은 '경기가 좋아져서 과열을 막으려 금리를 올린다'를 가정합니다. "
                "그때는 금리 상승 구간에서 주식이 오릅니다.\n\n"
                "비용충격(유가·환율)으로 어쩔 수 없이 올리는 국면에서는 기업 이익이 원가로 "
                "눌리는데 할인율만 올라갑니다. 교과서와 반대 방향이 나올 수 있습니다. "
                "1970년대 오일쇼크가 그런 경우였습니다.",
                icon="⚠️",
            )

    # ==========================================================================


st.divider()
# 설정
# ==========================================================================
st.divider()
with st.expander("⚙️ 사이클 밴드 · 금리 직접 입력"):
    st.markdown("##### 사이클 밴드")
    st.caption("비워두면 최근 이력에서 자동으로 최저·최고를 찾습니다. "
               "시장이 예상하는 최종금리를 고점에 넣으면 위치가 더 현실적으로 나옵니다.")
    c1, c2, c3 = st.columns(3)
    저점 = c1.number_input("사이클 저점(%)", min_value=0.0, max_value=25.0, step=0.25,
                        value=float(설정.get("cycle_low") or 0.0), format="%.2f")
    고점 = c2.number_input("사이클 고점(%)", min_value=0.0, max_value=25.0, step=0.25,
                        value=float(설정.get("cycle_high") or 0.0), format="%.2f")
    조회연수 = c3.number_input("자동 산출 기간(년)", min_value=1, max_value=15, step=1,
                          value=int(설정.get("lookback_years", 3)))
    st.caption("0 으로 두면 '자동'입니다.")

    st.markdown("##### 현재 금리 직접 입력")
    사용수동 = st.checkbox("자동 조회 대신 직접 입력한 금리를 쓰기",
                       value=설정.get("manual_rate") is not None)
    수동값 = st.number_input("현재 기준금리(%)", min_value=0.0, max_value=25.0, step=0.25,
                          value=float(설정.get("manual_rate") or 상태.rate), format="%.2f",
                          disabled=not 사용수동)

    st.markdown("##### 금리 변경 이력 추가")
    st.caption("API 키가 없을 때, 새 금리 결정이 나오면 여기에 한 줄씩 추가하세요.")
    기준df = pd.DataFrame(
        [{"날짜": datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
          if isinstance(d, str) else d, "금리(%)": float(v)}
         for d, v in 설정.get("추가이력", [])] or [{"날짜": None, "금리(%)": None}])
    기준df["날짜"] = pd.Series([x if isinstance(x, date) else None
                             for x in 기준df["날짜"]], dtype="object")
    기준df["금리(%)"] = pd.to_numeric(기준df["금리(%)"], errors="coerce")
    이력df = st.data_editor(
        기준df, num_rows="dynamic", width="stretch",
        key=f"달걀_이력_{st.session_state.get('달걀_표버전', 0)}",
        column_config={
            "날짜": st.column_config.DateColumn(format="YYYY-MM-DD",
                                              min_value=date(1990, 1, 1),
                                              max_value=date(2100, 12, 31)),
            "금리(%)": st.column_config.NumberColumn(min_value=0.0, max_value=25.0,
                                                   step=0.25, format="%.2f"),
        })

    if st.button("💾 설정 저장", type="primary", width="stretch"):
        새이력 = []
        for _, row in 이력df.iterrows():
            d, v = row.get("날짜"), row.get("금리(%)")
            if d is None or pd.isna(d) or pd.isna(v):
                continue
            d = d if isinstance(d, date) else pd.to_datetime(d).date()
            새이력.append([d.isoformat(), float(v)])
        설정.update({
            "country": 나라,
            "cycle_low": 저점 if 저점 > 0 else None,
            "cycle_high": 고점 if 고점 > 0 else None,
            "lookback_years": int(조회연수),
            "manual_rate": float(수동값) if 사용수동 else None,
            "추가이력": 새이력,
        })
        성공, 메시지 = storage.저장하기(저장키, 설정)
        st.cache_data.clear()
        (st.success if 성공 else st.error)(메시지)
        if 성공:
            st.rerun()

with st.expander("🔑 자동 조회 설정 (선택)"):
    상태표시 = "설정됨 ✓" if api_key else "없음 — 내장 기본값 사용 중"
    st.markdown(f"현재 {나라} API 키: **{상태표시}**")
    with st.expander("ℹ️ 자세히"):
        st.markdown(
            "키를 넣으면 기준금리를 자동으로 받아옵니다. 없어도 위의 "
            "**금리 변경 이력 추가**로 직접 관리할 수 있습니다.\n\n"
            "- 한국: [한국은행 ECOS](https://ecos.bok.or.kr/api/) 무료 발급 → `ecos_api_key`\n"
            "- 미국: [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) 무료 발급 → `fred_api_key`\n\n"
            "넣는 곳은 비밀번호와 같습니다. 내 PC 는 `.streamlit/secrets.toml`, "
            "Streamlit Cloud 는 앱 Settings → Secrets."
        )
    st.code('ecos_api_key = "발급받은_키"\nfred_api_key = "발급받은_키"', language="toml")
    if st.button("🔄 지금 다시 조회", width="stretch"):
        st.cache_data.clear()
        st.rerun()

저장_불러오기("egg_cycle", 설정, "금리사이클_설정", "_달걀_적용대기",
          도움말="사이클 밴드와 직접 입력한 금리 이력이 함께 저장됩니다.")
