import os
import sys
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import egg_cycle as EC  # noqa: E402

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
          "manual_rate": None, "lookback_years": 3, "추가이력": []}

if "달걀_설정" not in st.session_state:
    불러온 = storage.불러오기(저장키, {}) or {}
    설정 = dict(기본설정)
    설정.update({k: v for k, v in 불러온.items() if k in 기본설정})
    st.session_state["달걀_설정"] = 설정
    st.session_state.setdefault("달걀_표버전", 0)
st.session_state.setdefault("달걀_표버전", 0)
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
st.caption(f"데이터 출처: {출처} · 왼쪽 = 금리 상승(호황기), 오른쪽 = 금리 하락(불황기)")

# ==========================================================================
# 금리 추이
# ==========================================================================
st.divider()
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

# ==========================================================================
# 6개 국면 표
# ==========================================================================
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
