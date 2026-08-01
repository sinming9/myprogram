"""
==========================================================================
화면 공통 모듈 (모바일 대응)
==========================================================================
휴대폰 화면에서 보기 편하도록 공통 CSS 를 넣고,
자주 쓰는 표시 함수를 모아둔 곳입니다.

각 페이지 맨 위에서 ui.모바일_스타일() 한 줄만 호출하면 됩니다.
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-07-31"


import streamlit as st

_CSS = """
<style>
/* ==========================================================================
   라이트/다크 자동 대응
   색을 직접 지정하지 않고 반투명 회색 + currentColor 를 써서
   Streamlit 이 어떤 테마로 그려도 자연스럽게 묻히도록 했습니다.
   ========================================================================== */

.block-container { padding-top: 2.2rem; padding-bottom: 3rem; }

/* 숫자 지표(metric) 글자가 좁은 화면에서 잘리지 않게 */
[data-testid="stMetricValue"] { font-size: clamp(1.0rem, 4.2vw, 1.55rem); }
[data-testid="stMetricLabel"] { font-size: 0.78rem; opacity: .85; }
[data-testid="stMetricDelta"] { font-size: 0.75rem; }

/* 표는 좁은 화면에서 좌우 스크롤 */
[data-testid="stDataFrame"] { overflow-x: auto; }

/* 버튼 터치 영역 확보 */
.stButton > button, .stDownloadButton > button { min-height: 2.7rem; }

/* 카드 - 테마 무관 */
.card {
  background: color-mix(in srgb, currentColor 6%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 22%, transparent);
  border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
  color: inherit;
}
.card .t { font-size: .78rem; opacity: .70; margin-bottom: 4px; }
.card .v { font-size: 1.18rem; font-weight: 700; }
.card .s { font-size: .74rem; opacity: .65; margin-top: 3px; }

/* color-mix 를 모르는 구형 브라우저용 대비값 */
@supports not (background: color-mix(in srgb, red 50%, blue)) {
  .card { background: rgba(127,127,127,.09); border-color: rgba(127,127,127,.24); }
}

/* ---------- 휴대폰 (가로 640px 이하) ---------- */
@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 1.6rem; }
  h1 { font-size: 1.42rem !important; }
  h2 { font-size: 1.18rem !important; }
  h3 { font-size: 1.02rem !important; }

  [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .4rem !important; }
  [data-testid="stHorizontalBlock"] > div[data-testid="stColumn"],
  [data-testid="stHorizontalBlock"] > div[data-testid="column"] { min-width: 46% !important; }

  section[data-testid="stSidebar"] { width: 82vw !important; }
}
</style>
"""


def 모바일_스타일():
    st.markdown(_CSS, unsafe_allow_html=True)


def 카드(제목: str, 값: str, 부제: str = ""):
    부제html = f'<div class="s">{부제}</div>' if 부제 else ""
    st.markdown(
        f'<div class="card"><div class="t">{제목}</div>'
        f'<div class="v">{값}</div>{부제html}</div>',
        unsafe_allow_html=True,
    )


def 카드_줄(항목들, 열수=2):
    """항목들 = [(제목, 값, 부제), ...] 를 열수 개씩 나눠서 카드로 그립니다."""
    for i in range(0, len(항목들), 열수):
        묶음 = 항목들[i:i + 열수]
        cols = st.columns(len(묶음))
        for col, 항목 in zip(cols, 묶음):
            제목, 값 = 항목[0], 항목[1]
            부제 = 항목[2] if len(항목) > 2 else ""
            with col:
                카드(제목, 값, 부제)


def 원(v, 소수=0) -> str:
    try:
        return f"{float(v):,.{소수}f}원"
    except (TypeError, ValueError):
        return "-"


def 만원(v) -> str:
    try:
        return f"{float(v) / 10000:,.0f}만원"
    except (TypeError, ValueError):
        return "-"


def 억(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(f) >= 1e8:
        return f"{f / 1e8:,.2f}억원"
    return f"{f / 1e4:,.0f}만원"


def 사이드바_메뉴안내():
    st.sidebar.caption("휴대폰에서는 화면 왼쪽 위 **»** 를 눌러 메뉴를 엽니다.")


def 현재_테마() -> str:
    """'light' / 'dark' / '' (알 수 없음) 을 돌려줍니다.

    st.context.theme 는 최신 Streamlit 에만 있어서 없으면 조용히 넘어갑니다.
    """
    try:
        종류 = st.context.theme.type
        if 종류 in ("light", "dark"):
            return 종류
    except Exception:  # noqa: BLE001
        pass
    return ""


def 테마_안내():
    """사이드바에 현재 테마와 바꾸는 방법을 안내합니다."""
    종류 = 현재_테마()
    이름 = {"light": "라이트 ☀️", "dark": "다크 🌙"}.get(종류, "시스템 설정 따라감")
    st.sidebar.caption(
        f"버전 {모듈버전} · 화면 테마: {이름}  \n"
        "PC/휴대폰의 다크모드 설정을 자동으로 따라갑니다. "
        "직접 바꾸려면 우측 상단 **⋮ → Settings → Appearance** 에서 고르세요."
    )
