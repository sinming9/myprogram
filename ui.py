"""
==========================================================================
화면 공통 모듈 (모바일 대응 + 공통 디자인)
==========================================================================
휴대폰 화면에서 보기 편하도록 공통 CSS 를 넣고,
자주 쓰는 표시 함수를 모아둔 곳입니다.

각 페이지 맨 위에서 ui.모바일_스타일() 한 줄만 호출하면 됩니다.

[디자인 규칙]  페이지마다 색·간격이 달라지지 않도록 여기서 한 번만 정합니다.
 · 색은 아래 `색` 사전에서만 고릅니다. 페이지에서 직접 #RRGGBB 를 쓰지 않습니다.
 · 큰 숫자는 헤드라인(), 나란히 놓는 숫자는 카드_줄() 을 씁니다.
 · 차트는 항상 차트() 로 그립니다. 안에서 공통 테마를 입힙니다.
 · 라이트/다크 어느 테마에서도 읽히도록, 배경은 색을 직접 칠하지 않고
   currentColor 를 섞어 씁니다.
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-09-02"


import streamlit as st

# ==========================================================================
# 색 사전
# ==========================================================================
#  라이트·다크 양쪽에서 모두 읽히는 중간 톤만 골랐습니다.
#  너무 밝은 색(다크에서 눈부심)이나 너무 어두운 색(라이트에서 안 보임)은
#  일부러 넣지 않았습니다.
색 = {
    "파랑": "#2B6ED5",     # 기본 강조 · 내 몫(개인)
    "초록": "#18A57A",     # 좋음 · 증가 · 자산
    "빨강": "#C0392B",     # 주의 · 감소 · 부채
    "주황": "#E28A2B",     # 가족 몫(배우자)
    "보라": "#8E7CC3",     # 공동 명의
    "청록": "#1F6F5C",     # 환율 본선
    "하늘": "#3B7EA1",
    "회색": "#9AA3AF",     # 기준선 · 전국 분포
    "금색": "#C9A227",
}

# 여러 갈래를 한 차트에 그릴 때 쓰는 순서.
# 이 순서를 지키면 페이지끼리 색이 어긋나지 않습니다.
색순서 = [색["파랑"], 색["초록"], 색["주황"], 색["빨강"], 색["보라"], 색["하늘"]]

_CSS = r"""
<style>
/* ==========================================================================
   라이트/다크 자동 대응
   색을 직접 지정하지 않고 반투명 회색 + currentColor 를 써서
   Streamlit 이 어떤 테마로 그려도 자연스럽게 묻히도록 했습니다.
   ========================================================================== */

.block-container { padding-top: 2.2rem; padding-bottom: 3rem; }

/* ---------- 글자 크기 단계 ----------
   제목이 본문보다 과하게 크면 화면이 시끄러워집니다. 단계를 좁혔습니다. */
h1 { font-size: 1.72rem !important; letter-spacing: -.02em; margin-bottom: .1rem; }
h2 { font-size: 1.24rem !important; letter-spacing: -.01em;
     margin-top: 1.5rem !important; margin-bottom: .5rem !important; }
h3 { font-size: 1.06rem !important; margin-top: 1.1rem !important; }

/* 숫자 지표(metric) 글자가 좁은 화면에서 잘리지 않게 */
[data-testid="stMetricValue"] { font-size: clamp(1.0rem, 4.2vw, 1.5rem);
                                font-variant-numeric: tabular-nums; }
[data-testid="stMetricLabel"] { font-size: 0.78rem; opacity: .85; }
[data-testid="stMetricDelta"] { font-size: 0.75rem; }

/* 표는 좁은 화면에서 좌우 스크롤 + 숫자 자릿수 정렬 */
[data-testid="stDataFrame"] { overflow-x: auto; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  font-variant-numeric: tabular-nums;
}

/* 버튼 터치 영역 확보 */
.stButton > button, .stDownloadButton > button {
  min-height: 2.7rem; border-radius: 10px;
}

/* 구분선은 얇고 조용하게 */
hr { margin: 1.4rem 0 !important;
     border-color: color-mix(in srgb, currentColor 14%, transparent) !important; }

/* ---------- 카드 ---------- */
.card {
  background: color-mix(in srgb, currentColor 5%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
  border-radius: 12px; padding: 11px 13px; margin-bottom: 9px;
  color: inherit; height: 100%;
}
.card .t { font-size: .76rem; opacity: .68; margin-bottom: 4px; }
.card .v { font-size: 1.16rem; font-weight: 700; letter-spacing: -.01em;
           font-variant-numeric: tabular-nums; line-height: 1.25; }
.card .s { font-size: .73rem; opacity: .62; margin-top: 3px; line-height: 1.35; }

/* 왼쪽에 색 띠를 두른 강조 카드 */
.card.accent { border-left-width: 3px; padding-left: 11px; }

/* ---------- 헤드라인 (페이지 대표 숫자) ---------- */
.headline {
  background: color-mix(in srgb, currentColor 4%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  border-radius: 14px; padding: 15px 17px; margin: 2px 0 12px 0;
}
.headline .t { font-size: .78rem; opacity: .68; margin-bottom: 3px; }
.headline .v { font-size: clamp(1.6rem, 7.5vw, 2.15rem); font-weight: 750;
               letter-spacing: -.025em; line-height: 1.15;
               font-variant-numeric: tabular-nums; }
.headline .s { font-size: .8rem; opacity: .7; margin-top: 5px; line-height: 1.45; }

/* ---------- 뱃지 (오름/내림 같은 작은 표시) ---------- */
.pill {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: .72rem; font-weight: 650; line-height: 1.6;
  margin-right: 5px; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ---------- 소제목 ---------- */
.seclabel {
  font-size: .72rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; opacity: .55; margin: 18px 0 2px 0;
}
.sectitle { font-size: 1.14rem; font-weight: 700; letter-spacing: -.01em;
            margin: 0 0 2px 0; }
.secsub { font-size: .78rem; opacity: .62; margin: 0 0 10px 0; line-height: 1.45; }

/* color-mix 를 모르는 구형 브라우저용 대비값 */
@supports not (background: color-mix(in srgb, red 50%, blue)) {
  .card, .headline { background: rgba(127,127,127,.08);
                     border-color: rgba(127,127,127,.20); }
  hr { border-color: rgba(127,127,127,.20) !important; }
}


/* ==========================================================================
   Material Symbols 아이콘 폰트가 차단된 환경 대응
   Streamlit 은 아이콘을 구글 폰트(fonts.gstatic.com)로 그립니다.
   회사망·보안프로그램이 이를 막으면 "double_arrow_right" 같은 이름이
   글자 그대로 노출됩니다. 아래에서 중요한 것들을 일반 문자로 바꿔둡니다.
   (폰트가 정상일 때도 같은 모양이 나오므로 항상 안전합니다)
   ========================================================================== */

/* 사이드바 여는 버튼 → ☰ */
[data-testid="stSidebarCollapsedControl"] span,
[data-testid="collapsedControl"] span {
  font-size: 0 !important;
  line-height: 0 !important;
}
[data-testid="stSidebarCollapsedControl"] span::after,
[data-testid="collapsedControl"] span::after {
  content: "☰";
  font-family: inherit !important;
  font-size: 26px;
  line-height: 1;
}
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] { padding: 6px 10px !important; }

/* 사이드바 닫는 버튼 → × */
[data-testid="stSidebarCollapseButton"] span { font-size: 0 !important; }
[data-testid="stSidebarCollapseButton"] span::after {
  content: "×";
  font-family: inherit !important;
  font-size: 24px;
}

/* 비밀번호 보기/숨기기 → 눈 모양 */
[data-baseweb="input"] button span,
[data-testid="stTextInput"] button span {
  font-size: 0 !important;
}
[data-baseweb="input"] button span::after,
[data-testid="stTextInput"] button span::after {
  content: "👁";
  font-family: inherit !important;
  font-size: 17px;
}

/* 펼치기(expander) 화살표 → ▾ */
[data-testid="stExpander"] summary span[data-testid="stIconMaterial"],
[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {
  font-size: 0 !important;
}
[data-testid="stExpander"] summary span[data-testid="stIconMaterial"]::after,
[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"]::after {
  content: "▾";
  font-family: inherit !important;
  font-size: 13px;
  opacity: .7;
}

/* 위에서 못 잡은 나머지 아이콘 - 폰트가 막혔을 때 이름이 글자로 튀어나오는
   것보다는 안 보이는 편이 낫습니다. 버튼에는 글자 라벨이 따로 있습니다. */
span[data-testid="stIconMaterial"] {
  font-size: 0 !important;
  min-width: 0 !important;
}
span[data-testid="stIconMaterial"]::after {
  content: "•";
  font-family: inherit !important;
  font-size: 12px;
  opacity: .45;
}

/* 화면 안 이동 메뉴 */
.navrow { margin: -6px 0 14px 0; }
.navrow [data-testid="stHorizontalBlock"] { gap: .3rem !important; }
[data-testid="stPageLink"] a { font-size: .84rem; }

/* 탭은 조금 더 또렷하게 */
[data-testid="stTabs"] [data-baseweb="tab"] { font-size: .92rem; }

/* ---------- 휴대폰 (가로 640px 이하) ---------- */
@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 1.6rem; }
  h1 { font-size: 1.38rem !important; }
  h2 { font-size: 1.12rem !important; }
  h3 { font-size: 1.0rem !important; }

  [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .4rem !important; }
  [data-testid="stHorizontalBlock"] > div[data-testid="stColumn"],
  [data-testid="stHorizontalBlock"] > div[data-testid="column"] { min-width: 46% !important; }

  section[data-testid="stSidebar"] { width: 82vw !important; }
}
</style>
"""


def 모바일_스타일():
    st.markdown(_CSS, unsafe_allow_html=True)


# ==========================================================================
# 숫자 표시
# ==========================================================================

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


def 부호억(v) -> str:
    """증감 표시용. 0 보다 크면 + 를 붙입니다."""
    글 = 억(v)
    try:
        return ("+" + 글) if float(v) > 0 else 글
    except (TypeError, ValueError):
        return 글


# ==========================================================================
# 카드 · 헤드라인 · 뱃지
# ==========================================================================

def 카드(제목: str, 값: str, 부제: str = "", 색이름=None):
    """작은 숫자 카드 하나.

    색이름 을 주면 왼쪽에 그 색 띠를 둘러 강조합니다.
    (`색` 사전의 키 또는 #RRGGBB 를 그대로 넣어도 됩니다)
    """
    부제html = f'<div class="s">{_간단서식(부제)}</div>' if 부제 else ""
    덧 = ""
    if 색이름:
        c = 색.get(색이름, 색이름)
        덧 = f' accent" style="border-left-color:{c}'
    st.markdown(
        f'<div class="card{덧}"><div class="t">{제목}</div>'
        f'<div class="v">{값}</div>{부제html}</div>',
        unsafe_allow_html=True,
    )


def 카드_줄(항목들, 열수=2):
    """항목들 = [(제목, 값, 부제, 색이름), ...] 를 열수 개씩 나눠서 카드로 그립니다.

    부제·색이름은 없어도 됩니다. (제목, 값) 만 넘겨도 그대로 동작합니다.
    """
    for i in range(0, len(항목들), 열수):
        묶음 = 항목들[i:i + 열수]
        cols = st.columns(len(묶음))
        for col, 항목 in zip(cols, 묶음):
            제목, 값 = 항목[0], 항목[1]
            부제 = 항목[2] if len(항목) > 2 else ""
            색이름 = 항목[3] if len(항목) > 3 else None
            with col:
                카드(제목, 값, 부제, 색이름)


def 뱃지(문장: str, 종류: str = "중립") -> str:
    """작은 알약 모양 표시의 HTML 을 돌려줍니다. (그리지 않고 문자열만 반환)

    종류 = 좋음 / 나쁨 / 강조 / 중립
    """
    바탕, 글자 = {
        "좋음": ("rgba(24,165,122,.16)", 색["초록"]),
        "나쁨": ("rgba(192,57,43,.16)", 색["빨강"]),
        "강조": ("rgba(43,110,213,.16)", 색["파랑"]),
    }.get(종류, ("color-mix(in srgb, currentColor 10%, transparent)", "inherit"))
    return f'<span class="pill" style="background:{바탕};color:{글자}">{문장}</span>'


def 헤드라인(라벨: str, 값: str, 부제: str = "", 뱃지들=()):
    """페이지 대표 숫자 하나를 큼직하게. 뱃지들 = 뱃지() 결과 문자열 목록."""
    줄 = "".join(뱃지들)
    뱃지html = f'<div style="margin-top:7px">{줄}</div>' if 줄 else ""
    부제html = f'<div class="s">{_간단서식(부제)}</div>' if 부제 else ""
    st.markdown(
        f'<div class="headline"><div class="t">{라벨}</div>'
        f'<div class="v">{값}</div>{부제html}{뱃지html}</div>',
        unsafe_allow_html=True,
    )


def _간단서식(글: str) -> str:
    """**굵게** 와 `코드` 만 HTML 로 바꿉니다.

    섹션()·카드() 는 HTML 로 그리므로 마크다운이 통하지 않습니다.
    그대로 두면 별표가 글자로 보여서, 자주 쓰는 두 가지만 바꿔줍니다.
    """
    import re
    글 = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", str(글 or ""))
    return re.sub(r"`(.+?)`",
                  r'<code style="font-size:.92em;opacity:.85">\1</code>', 글)


def 섹션(제목: str, 부제: str = "", 라벨: str = ""):
    """소제목. st.subheader 보다 조용하고 부제를 붙일 수 있습니다.

    부제에는 **굵게** 와 `코드` 표기를 쓸 수 있습니다.
    """
    조각 = []
    if 라벨:
        조각.append(f'<div class="seclabel">{라벨}</div>')
    조각.append(f'<div class="sectitle">{_간단서식(제목)}</div>')
    if 부제:
        조각.append(f'<div class="secsub">{_간단서식(부제)}</div>')
    st.markdown("".join(조각), unsafe_allow_html=True)


def 선택줄(라벨: str, 항목들, key: str, format_func=None, 기본=0,
         label_visibility="collapsed"):
    """가로로 늘어놓는 선택 줄.

    st.segmented_control 이 있으면 그걸 쓰고(더 깔끔합니다), 없으면 radio 로
    떨어집니다. 어느 쪽이든 항상 하나가 골라진 값을 돌려줍니다.
    """
    목록 = list(항목들)
    if not 목록:
        return None
    기본값 = 목록[min(max(기본, 0), len(목록) - 1)]
    꾸미기 = format_func or (lambda x: x)
    if hasattr(st, "segmented_control"):
        고른 = st.segmented_control(라벨, 목록, key=key, default=기본값,
                                  format_func=꾸미기,
                                  label_visibility=label_visibility)
        # segmented_control 은 고른 것을 한 번 더 누르면 None 을 돌려줍니다.
        return 고른 if 고른 is not None else 기본값
    return st.radio(라벨, 목록, index=목록.index(기본값), horizontal=True,
                    key=key, format_func=꾸미기,
                    label_visibility=label_visibility)


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


# ==========================================================================
# 화면 안 이동 메뉴
#   휴대폰에서 사이드바를 못 열어도(아이콘 폰트 차단 등) 페이지를 옮길 수 있게
#   각 페이지 맨 위에 넣는 링크 줄입니다.
# ==========================================================================

메뉴목록 = [
    ("Home.py", "🗂️", "홈"),
    ("pages/1_🏦_대출_상환_계산기.py", "🏦", "대출"),
    ("pages/2_💱_환전_타이밍.py", "💱", "환전"),
    ("pages/3_🏠_재산세_종부세.py", "🏠", "재산세"),
    ("pages/4_💰_연봉_급여_관리.py", "💰", "연봉"),
    ("pages/5_🥚_금리_사이클.py", "🥚", "금리"),
    ("pages/6_🏷️_양도세_계산기.py", "🏷️", "양도세"),
    ("pages/7_📊_자산배분.py", "📊", "자산배분"),
    ("pages/7_💎_순자산.py", "💎", "순자산"),
    ("pages/7_🧓_연금.py", "🧓", "연금"),
    ("pages/8_📥_자료_가져오기.py", "📥", "가져오기"),
    ("pages/9_➕_내_프로그램.py", "➕", "내 프로그램"),
]


def 페이지_메뉴(현재파일: str = ""):
    """페이지 맨 위에 이동 링크를 한 줄로 깝니다.

    현재파일 에는 __file__ 을 넘기면 그 항목은 빼고 보여줍니다.
    """
    현재 = (현재파일 or "").replace("\\", "/").split("/")[-1]
    보일것 = [m for m in 메뉴목록 if not (현재 and m[0].split("/")[-1] == 현재)]
    if not 보일것:
        return
    st.markdown('<div class="navrow">', unsafe_allow_html=True)
    한줄 = 4
    for i in range(0, len(보일것), 한줄):
        묶음 = 보일것[i:i + 한줄]
        cols = st.columns(len(묶음))
        for col, (경로, 아이콘, 이름) in zip(cols, 묶음):
            with col:
                st.page_link(경로, label=f"{아이콘} {이름}")
    st.markdown('</div>', unsafe_allow_html=True)


# ==========================================================================
# 차트 그리기 — 고정형 + 공통 테마
# ==========================================================================
#  확대·축소·이동을 끕니다. 휴대폰에서 스크롤하다 차트를 건드리면
#  의도치 않게 확대되거나 그래프가 밀려서 보기 나빠집니다.
#  마우스를 올렸을 때 값이 보이는 것(hover)은 그대로 둡니다.
#
#  더불어 공통 테마를 입힙니다. 배경을 투명하게 두면 라이트·다크 어느
#  테마에서도 페이지 배경과 이어져 보입니다. 격자선도 반투명 회색이라
#  테마에 상관없이 은은하게 깔립니다.

차트_설정 = {
    "displayModeBar": False,   # 위쪽 카메라·돋보기 아이콘 줄 숨김
    "scrollZoom": False,       # 휠·두 손가락 확대 끔
    "doubleClick": False,      # 두 번 눌러 초기화 끔
    "displaylogo": False,
    "staticPlot": False,       # hover 는 살립니다
}

_격자 = "rgba(128,128,128,.16)"
_축선 = "rgba(128,128,128,.35)"


def 차트_테마(fig):
    """모든 차트에 같은 여백·글꼴·격자선을 입힙니다.

    ※ 이미 margin 이나 legend 를 정해둔 차트는 그 값을 지키고,
      정하지 않은 것만 채웁니다. (기존 페이지를 건드리지 않기 위해)
    """
    try:
        정해진여백 = getattr(fig.layout.margin, "l", None) is not None
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(size=12),
            hoverlabel=dict(font_size=12),
            legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0,
                        font=dict(size=11)),
        )
        if not 정해진여백:
            fig.update_layout(margin=dict(l=8, r=8, t=28, b=8))
        fig.update_xaxes(showgrid=False, zeroline=False,
                         linecolor=_축선, ticks="outside",
                         tickcolor=_축선, ticklen=4)
        fig.update_yaxes(gridcolor=_격자, zeroline=False, linewidth=0)
    except Exception:  # noqa: BLE001
        pass
    return fig


def 차트(fig, key=None, 테마=True, **k):
    """확대·축소가 안 되는 고정 차트로 그립니다.

    st.plotly_chart 대신 이걸 쓰면 앱 전체가 같은 방식으로 동작합니다.
    테마=False 를 주면 공통 테마를 입히지 않습니다 (게이지·도넛 등).
    """
    if 테마:
        차트_테마(fig)
    try:
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)
    except Exception:  # noqa: BLE001
        pass
    st.plotly_chart(fig, config=차트_설정, width="stretch", key=key, **k)


def 미니차트(점들, 색이름="파랑", key=None, 높이=110, 채우기=True,
          hover="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>"):
    """축도 눈금도 없는 작은 추세선(스파크라인). 점들 = [(x, y), ...]

    값이 0 부근에서 시작하지 않는 환율 같은 자료는 채우기=False 가 낫습니다.
    (0 까지 칠하면 변동이 납작하게 보입니다)
    """
    import plotly.graph_objects as go
    점들 = list(점들 or [])
    if not 점들:
        return
    c = 색.get(색이름, 색이름)
    fig = go.Figure(go.Scatter(
        x=[p[0] for p in 점들], y=[p[1] for p in 점들], mode="lines",
        line=dict(color=c, width=2),
        fill="tozeroy" if 채우기 else None,
        fillcolor="rgba(43,110,213,.10)" if 채우기 else None,
        hovertemplate=hover))
    fig.update_layout(height=높이, margin=dict(l=0, r=0, t=4, b=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)")
    차트(fig, key=key, 테마=False)
