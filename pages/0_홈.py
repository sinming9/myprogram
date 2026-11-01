"""
==========================================================================
개인 대시보드 - 첫 화면
==========================================================================
(예전에는 Home.py 에 있었습니다. 사이드바를 묶음별로 나누려면 Home.py 가
 st.navigation 을 맡아야 해서, 첫 화면 내용은 이 파일로 옮겼습니다.)

[설계 원칙]
 · 첫 화면은 빨라야 합니다. 그래서 **저장된 자료로 계산만 하고**
   시세·환율 같은 네트워크 조회는 하지 않습니다.
 · 투자자산 숫자는 아침 브리핑이 매일 남기는 기록(portfolio_history)을
   씁니다. 텔레그램과 같은 함수(engines.portfolio 의 기록_* · brief 의
   ⚡ 기준값)를 써서 두 곳의 숫자가 같습니다.

[구성] (2026-11 개편 — 시안 기준)
 탭  투자자산(기본) / 시장 / 계산기
   투자자산  요약 카드 · 원금과 평가액 추이 · 계좌 구성 · 일반 계좌 목표 비중
             · 보유 종목 · 작은 카드 4개(기준금리·환율·대출·순자산)
   시장      기준금리(한·미) · 환율
   계산기    연봉 · 재산세·종부세 · 양도세 (예전 첫 화면 카드를 옮긴 것)

[색 규칙]  상승 빨강 #FF7A85 · 하락 파랑 #6FA3FF (한국식) · 경고 주황 #F5A15A
           그 밖에는 회색만. 대출 감소도 '줄었다(파랑)' 로 같은 규칙.
==========================================================================
"""

import os
import re
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import addons  # noqa: E402
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import brief as BR  # noqa: E402
from engines import portfolio as PF  # noqa: E402

require_login(page_title="개인 대시보드", page_icon="🗂️", layout="wide")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

# ==========================================================================
# 색 · 모양
# ==========================================================================
빨강, 파랑, 주황 = "#FF7A85", "#6FA3FF", "#F5A15A"
글자, 흐림, 더흐림 = "#E6E8EE", "#9AA3B2", "#6B7385"
카드, 테두리 = "#161B26", "#262C3A"
회색들 = ["#E6E8EE", "#A9B0BE", "#7A8292", "#5A6170", "#3E4452", "#2E3340"]

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
.st-key-hwrap, .st-key-hwrap * {{ font-family: 'Noto Sans KR', sans-serif; }}
.st-key-hwrap [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-hc_"]),
.st-key-hwrap [class*="st-key-hc_"] {{
  background: {카드}; border-color: {테두리} !important; border-radius: 14px;
}}
.hc-label {{ color: {흐림}; font-size: .85rem; margin-bottom: .2rem; }}
.hc-big {{ color: {글자}; font-size: 2.3rem; font-weight: 700; line-height: 1.15; }}
.hc-mid {{ color: {글자}; font-size: 1.45rem; font-weight: 700; line-height: 1.2; }}
.hc-sub {{ color: {흐림}; font-size: .82rem; margin-top: .15rem; }}
.hc-title {{ color: {글자}; font-weight: 700; font-size: 1rem; margin-bottom: .4rem; }}
.hc-flash {{ background: #1C2230; border-radius: 10px; padding: .55rem .9rem;
             color: {글자}; font-size: .9rem; margin-top: .6rem; }}
.hc-row {{ display: flex; justify-content: space-between; padding: .45rem .2rem;
           border-bottom: 1px solid {테두리}; color: {글자}; font-size: .9rem; }}
.hc-row span.r {{ color: {흐림}; display: inline-block; min-width: 4.2rem;
                  margin-left: 1.2rem; text-align: right; }}
.hc-dot {{ display: inline-block; width: .65rem; height: .65rem; border-radius: 2px;
           margin-right: .45rem; vertical-align: middle; }}
.hc-bar {{ position: relative; height: 12px; background: {테두리}; border-radius: 6px;
           margin: .35rem 0 .25rem; }}
.hc-bar > .fill {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 6px; }}
.hc-bar > .goal {{ position: absolute; top: -4px; bottom: -4px; width: 2px;
                   background: {글자}; }}
.hc-item {{ display: flex; justify-content: space-between; color: {글자};
            font-size: .9rem; margin-top: .55rem; }}
@media (max-width: 640px) {{
  .st-key-hwrap [data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    min-width: 100% !important; flex: 1 1 100% !important;
  }}
  .st-key-hwrap [class*="st-key-hc_"] [data-testid="stColumn"] {{ margin-bottom: .7rem; }}
  .hc-big {{ font-size: 1.8rem; }}
}}
</style>
""", unsafe_allow_html=True)


def 글자만(이름: str) -> str:
    """'📈 시장' → '시장'. 이모지는 사이드바 메뉴에만 남깁니다."""
    return re.sub(r"^[^\w가-힣]+", "", 이름).strip()


def _날짜(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _md(d) -> str:
    d = _날짜(d) if not isinstance(d, date) else d
    return f"{d.month}/{d.day}" if d else "-"


def _요일(d) -> str:
    d = _날짜(d) if not isinstance(d, date) else d
    return f"{d.month}/{d.day}({BR.요일이름[d.weekday()]})" if d else "-"


def 색(값) -> str:
    v = PF._숫자(값)
    return 빨강 if v > 0 else (파랑 if v < 0 else 흐림)


def 화살(값) -> str:
    v = PF._숫자(값)
    return "▲" if v > 0 else ("▼" if v < 0 else "―")


def 짧은계좌(이름) -> str:
    return BR.계좌_짧게.get(str(이름), str(이름))


def 칸(key):
    """시안의 카드 상자 (배경 #161B26 · 테두리 #262C3A · 모서리 14px)."""
    return st.container(border=True, key=f"hc_{key}")


# ==========================================================================
# 요약 함수 — 시장·계산기 탭과 아래 작은 카드가 씁니다 (네트워크 없음)
# ==========================================================================
#   이름 · 경로 · 값 · 변화(글자/None) · 추이(숫자 목록) · 기준 · 해석
문제 = []


def _안전(이름, 함수):
    """한 프로그램의 요약이 실패해도 나머지는 보이게 합니다."""
    try:
        return 함수()
    except Exception as e:  # noqa: BLE001
        문제.append(f"{이름}: {type(e).__name__}")
        return None


def _변화(지금, 전, 단위="억"):
    if 전 is None or 지금 is None or 지금 == 전:
        return None
    차 = 지금 - 전
    if 단위 == "%p":
        return f"{차:+.2f}%p"
    글 = ui.억(abs(차)) if 단위 == "억" else ui.원(abs(차))
    return ("+" if 차 > 0 else "-") + 글


def 순자산_요약():
    설정 = storage.불러오기("networth", None)
    if not 설정:
        return None
    값열 = "순자산" if 설정.get("기록기준", "가구") == "가구" else "개인순자산"
    기록 = sorted((_날짜(r.get("날짜")), float(r[값열])) for r in (설정.get("기록") or [])
                if _날짜(r.get("날짜")) and r.get(값열) not in (None, ""))
    if not 기록:
        return None
    마지막날, 지금 = 기록[-1]
    return {"이름": "순자산 (가구)" if 값열 == "순자산" else "순자산 (내 몫)",
            "값": ui.억(지금), "기준날": 마지막날,
            "묵음": (date.today() - 마지막날).days,
            "변화": _변화(지금, 기록[-2][1] if len(기록) >= 2 else None)}


def 대출_요약():
    설정 = storage.불러오기("loan", None)
    if not 설정:
        return None
    from engines.loan import 스케줄_생성, 요약 as 대출요약
    금리 = [{"start_month": r["시작회차"], "rate": r["금리(%)"]}
          for r in (설정.get("금리스케줄") or [])]
    if not any(r["start_month"] == 1 for r in 금리):
        금리.append({"start_month": 1, "rate": float(설정.get("연이율", 3.5))})
    중도 = []
    for r in (설정.get("중도상환목록") or []):
        try:
            중도.append({"date": date.fromisoformat(str(r["날짜"])[:10]),
                       "amount": r["금액"], "method": r["방식"],
                       "interest": r.get("이자(직접입력)"),
                       "fee": r.get("수수료(직접입력)")})
        except Exception:  # noqa: BLE001
            pass
    결과, _경고 = 스케줄_생성(
        int(설정["원금"]), date.fromisoformat(str(설정["대출시작일"])[:10]),
        date.fromisoformat(str(설정["첫납입일"])[:10]), int(설정["상환개월수"]),
        금리, 중도, 설정.get("상환방식", "원리금균등"),
        bool(설정.get("영업일_적용", True)),
        설정.get("이자정산방식", "원금분만"),
        float(설정.get("수수료율", 0)), int(설정.get("면제기간_개월", 36)))
    s = 대출요약(결과)
    정기 = [r for r in 결과 if r["구분"] == "정기납입"]
    남은 = [r for r in 정기 if r["날짜"] >= date.today()]
    잔액 = 남은[0]["잔액"] if 남은 else 0
    월납 = 남은[0]["납입액"] if 남은 else 0
    return {"이름": "대출 잔액", "경로": "pages/1_🏦_대출_상환_계산기.py",
            "값": ui.억(잔액), "추이": [r["잔액"] for r in 정기][::3],
            "해석": f"월 {월납 / 1e4:,.0f}만 · 남은 {len(남은)}회 · 완납 {s['완납일']}"}


def 재산세_요약():
    자료 = storage.불러오기("property_tax", None)
    if not 자료 or not 자료.get("부동산"):
        return None
    from engines.property_tax import (AGE_OPTIONS, HOLD_OPTIONS, PropertyRow,
                                      calculate)
    목록 = [PropertyRow(name=str(p.get("이름") or ""),
                     gongsi_manwon=float(p.get("공시가격(만원)") or 0),
                     share_pct=float(p.get("지분(%)") or 100))
          for p in 자료["부동산"] if p.get("공시가격(만원)")]
    if not 목록:
        return None
    고지 = sum(float(p.get("실제 7월 고지액(선택)") or 0) for p in 자료["부동산"])
    r = calculate(목록, bool(자료.get("is_one", True)),
                 int(자료.get("house_count", 1)),
                 AGE_OPTIONS.get(자료.get("age_key"), 0.0),
                 HOLD_OPTIONS.get(자료.get("hold_key"), 0.0),
                 고지 if 고지 > 0 else None)
    연간 = r.july_total + r.sep_total + r.j_total
    기록 = sorted((자료.get("history") or []), key=lambda h: h.get("year", 0))
    올해 = date.today().year
    작년 = next((h["total"] for h in reversed(기록)
               if int(h.get("year", 0)) < 올해 and h.get("total") is not None), None)
    return {"이름": "재산세·종부세", "경로": "pages/3_🏠_부동산_세금.py",
            "값": ui.원(연간), "변화": _변화(연간, 작년, "원"),
            "추이": [h["total"] for h in 기록 if h.get("total") is not None],
            "기준": f"{올해}년",
            "해석": (f"부동산 {len(목록)}건 · 7월 {ui.억(r.july_total)} · "
                     f"9월 {ui.억(r.sep_total)} · 12월 {ui.억(r.j_total)}")}


def 연봉_요약():
    자료 = storage.불러오기("salary", None)
    if not 자료:
        return None
    from engines import salary as S
    기록 = S.dashboard_records(자료)
    if not 기록:
        return None
    최근 = 기록[-1]
    목표, _목표율 = S.recommended_salary(기록)
    return {"이름": "연봉", "경로": "pages/4_💰_연봉_급여_관리.py",
            "값": ui.원(최근["base_sal"]),
            "변화": (f"{최근['raise']:+.2f}%" if 최근["raise"] is not None else None),
            "추이": [r["base_sal"] for r in 기록], "기준": f"{최근['year']}년",
            "해석": (f"내년 권장 {ui.억(목표)}" if 목표 else "비교 기준 없음")}


def 양도세_요약():
    설정 = storage.불러오기("capital_gains", None)
    if not 설정 or not 설정.get("양도가액"):
        return None
    from engines import capital_gains as CG
    입력 = CG.양도입력(
        취득일=date.fromisoformat(str(설정["취득일"])[:10]),
        양도일=date.fromisoformat(str(설정["양도일"])[:10]),
        취득가액=float(설정["취득가액"]), 양도가액=float(설정["양도가액"]),
        필요경비=float(설정.get("필요경비") or 0),
        리모델링분담금=float(설정.get("리모델링분담금") or 0),
        거주개월=int(설정.get("거주개월") or 0),
        주택수=int(설정.get("주택수") or 1),
        취득시_조정대상지역=bool(설정.get("취득시_조정대상지역")),
        양도시_조정대상지역=bool(설정.get("양도시_조정대상지역")),
        세법기준=설정.get("세법기준", "양도일 자동"),
        공제제도기준=설정.get("공제제도기준", "양도일 자동"),
        기본공제확대=bool(설정.get("기본공제확대")),
        일시적2주택=bool(설정.get("일시적2주택")))
    r = CG.계산(입력)
    return {"이름": "양도세", "경로": "pages/3_🏠_부동산_세금.py",
            "값": ("비과세" if r.비과세인가 else ui.억(r.총세액)),
            "기준": f"{입력.양도일.month}/{입력.양도일.day} 양도",
            "해석": (r.비과세사유[:40] if r.비과세인가
                     else f"차익의 {r.유효세율:.1f}% · 실수령 {ui.억(r.실수령액)}")}


def 금리_요약(나라):
    """나라 = "KR" / "US". 금리 사이클 페이지가 저장해 둔 값(rate_cache)을 씁니다."""
    from engines import egg_cycle as EC
    설정 = storage.불러오기("egg_cycle", {}) or {}
    내나라 = 설정.get("country", "KR") == 나라
    추가 = [(d, v) for d, v in 설정.get("추가이력", [])] if 내나라 else []
    보관 = storage.불러오기(f"rate_cache_{나라}", None) or {}
    if 보관.get("이력"):
        점들 = [(date.fromisoformat(d), float(v)) for d, v in 보관["이력"]]
        점들 += [(date.fromisoformat(str(d)[:10]), float(v)) for d, v in 추가]
        if max(p[0] for p in 점들) < date.today():
            점들.append((date.today(), sorted(점들)[-1][1]))
        이력 = EC.RateHistory(점들).sort()
        기준날 = _날짜(보관.get("날짜"))
    else:
        이력, _출처, _오류 = EC.이력_불러오기(나라, None, 추가)
        기준날 = None
    수동 = 설정.get("manual_rate") if 내나라 else None
    if 수동:
        이력 = EC.RateHistory(list(이력.points) + [(date.today(), float(수동))]).sort()
    상태 = EC.compute_state(이력, EC.CycleConfig(
        country=나라,
        cycle_low=설정.get("cycle_low") if 내나라 else None,
        cycle_high=설정.get("cycle_high") if 내나라 else None,
        lookback_years=int(설정.get("lookback_years", 3))), "")
    날짜, 값 = 이력.계단_시계열()
    시작 = date(date.today().year - 3, date.today().month, 1)
    return {"이름": "한국 기준금리" if 나라 == "KR" else "미국 기준금리",
            "경로": "pages/5_🥚_금리_사이클.py", "금리": 상태.rate,
            "값": f"{상태.rate:.2f}%",
            "추이": [v for d, v in zip(날짜, 값) if d >= 시작] or list(값),
            "기준": (_md(기준날) if 기준날 else "내장값"),
            "해석": f"{상태.phase.name} · {상태.phase.action}"}


def 작은_지표(item):
    """시장·계산기 탭의 카드 — st.metric (변화 색은 회색 하나로)."""
    추이 = [float(v) for v in (item.get("추이") or []) if v is not None]
    인자 = dict(label=item["이름"], value=item["값"], border=True,
              delta=item.get("변화"), delta_color="off")
    if len(추이) >= 2:
        인자.update(chart_data=추이, chart_type="line")
    st.metric(**인자)
    st.caption(" · ".join(x for x in (
        (f"{item['기준']} 기준" if item.get("기준") else ""), item.get("해석", "")) if x))


# ==========================================================================
# 투자자산 — 아침 브리핑 기록으로
# ==========================================================================
def 투자자료():
    기록 = storage.불러오기("portfolio_history", None)
    스냅 = [s for s in PF.기록_정렬(기록) if PF._숫자(s.get("총액")) > 0]
    if not 스냅:
        return None
    오늘 = 스냅[-1]
    날 = str(오늘["날짜"])
    주초 = PF.기록_주초(스냅, 날)
    d = date.fromisoformat(날)
    달전 = (d.replace(day=1) - timedelta(days=1))          # 지난달 같은 날 (없으면 말일)
    달전 = 달전.replace(day=min(d.day, 달전.day)).isoformat()
    한달전 = max((s for s in 스냅 if str(s["날짜"]) <= 달전),
              key=lambda s: s["날짜"], default={})
    일주전 = (d - timedelta(days=6)).isoformat()
    return {"스냅": 스냅, "오늘": 오늘, "날": 날, "주초": 주초, "한달전": 한달전,
            "일별_전체": PF.기록_일별변동(스냅),
            "일별_주": PF.기록_일별변동(스냅, 일주전),
            "자산": storage.불러오기("portfolio", None) or {}}


def 요약_카드(자):
    오늘, 주초, 한달전 = 자["오늘"], 자["주초"], 자["한달전"]
    총액 = PF._숫자(오늘["총액"])
    률, 액 = BR._수익률(오늘)
    with 칸("summary"):
        왼, 가, 나 = st.columns([2.2, 1, 1])
        with 왼:
            st.markdown('<div class="hc-label">투자자산 합계</div>'
                        f'<div class="hc-big">{BR.만원(총액)}</div>'
                        + (f'<div class="hc-sub" style="color:{색(액)}">원금 대비 '
                           f'{률:+.1f}% ({BR.증감(액)})</div>' if 률 is not None else ""),
                        unsafe_allow_html=True)
        with 가:
            if 주초:
                옛 = PF._숫자(주초["총액"])
                차 = 총액 - 옛
                입출금 = PF.기록_입출금(오늘, 주초)
                st.markdown(
                    f'<div class="hc-label">이번 주 (vs {_md(주초["날짜"])})</div>'
                    f'<div class="hc-mid" style="color:{색(차)}">{화살(차)}{BR.만원(차)}</div>'
                    f'<div class="hc-sub">입출금 {BR.증감(입출금)} · 시장 {BR.증감(차 - 입출금)}</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown('<div class="hc-label">이번 주</div>'
                            '<div class="hc-sub">이번 주 기록 수집 중</div>',
                            unsafe_allow_html=True)
        with 나:
            if 한달전:
                옛 = PF._숫자(한달전["총액"])
                차 = 총액 - 옛
                st.markdown(
                    f'<div class="hc-label">지난달 대비 (vs {_md(한달전["날짜"])})</div>'
                    f'<div class="hc-mid" style="color:{색(차)}">{화살(차)}{BR.만원(차)}</div>'
                    f'<div class="hc-sub">{차 / 옛 * 100:+.2f}%</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown('<div class="hc-label">지난달 대비</div>'
                            '<div class="hc-sub">기록 수집 중</div>', unsafe_allow_html=True)
        # ⚡ 큰 변동 — 텔레그램 주간판과 같은 기준(입출금 뺀 시장 변동 ±1.5%)
        일별 = 자["일별_주"]
        if any(abs(x["시장률"]) >= BR.큰변동_총자산 for x in 일별):
            조각 = []
            내림 = [x for x in 일별 if x["시장률"] < 0]
            오름 = [x for x in 일별 if x["시장률"] > 0]
            for 말, 무리, 고르기 in (("최대 하락", 내림, min), ("최대 상승", 오름, max)):
                if 무리:
                    x = 고르기(무리, key=lambda x: x["시장률"])
                    조각.append(f'{말} {_요일(x["날짜"])} <span style="color:{색(x["차이"])}">'
                              f'{BR.증감(x["차이"])} ({x["변동률"]:+.2f}%)</span>')
            st.markdown(f'<div class="hc-flash"><b style="color:{주황}">큰 변동</b>　'
                        f'이번 주 {" · ".join(조각)}</div>', unsafe_allow_html=True)


def 추이_차트(자):
    with 칸("trend"):
        머리, 버튼 = st.columns([1, 1])
        머리.markdown('<div class="hc-title">원금과 평가액 추이</div>', unsafe_allow_html=True)
        with 버튼:
            기간 = st.segmented_control("기간", ["1주", "1개월", "3개월", "전체"],
                                      default="3개월", key="home_기간",
                                      label_visibility="collapsed") or "3개월"
        끝 = date.fromisoformat(자["날"])
        시작 = {"1주": 끝 - timedelta(days=7), "1개월": 끝 - timedelta(days=31),
              "3개월": 끝 - timedelta(days=92)}.get(기간, date(1900, 1, 1)).isoformat()
        스냅 = [s for s in 자["스냅"] if str(s["날짜"]) >= 시작]
        if len(스냅) < 2:
            st.caption("기록 수집 중 — 이틀 이상 쌓이면 그래프가 나옵니다.")
            return
        x = [str(s["날짜"]) for s in 스냅]
        평가 = [PF._숫자(s["총액"]) / 1e8 for s in 스냅]
        원금쌍 = [(str(s["날짜"]), PF._숫자(s.get("원금")) / 1e8, PF._숫자(s["총액"]) / 1e8)
               for s in 스냅 if PF._숫자(s.get("원금")) > 0]
        fig = go.Figure()
        if 원금쌍:
            # 원금(점선 계단) → 같은 날짜의 평가액으로 그 사이를 옅게 채웁니다
            fig.add_trace(go.Scatter(
                x=[p[0] for p in 원금쌍], y=[p[1] for p in 원금쌍], name="원금",
                mode="lines", line=dict(color=흐림, width=1.6, dash="dash", shape="hv"),
                hovertemplate="원금 %{y:.3f}억<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[p[0] for p in 원금쌍], y=[p[2] for p in 원금쌍], name="수익 구간",
                mode="lines", line=dict(width=0), fill="tonexty",
                fillcolor="rgba(255,122,133,0.13)", hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=x, y=평가, name="평가액", mode="lines",
            line=dict(color=글자, width=2.4),
            hovertemplate="%{x}<br>평가액 %{y:.3f}억<extra></extra>"))
        # ⚡ 큰 변동이 있었던 날 — 점 + 금액 라벨
        큰날 = [v for v in 자["일별_전체"]
              if abs(v["시장률"]) >= BR.큰변동_총자산 and v["기록일"] >= 시작]
        if 큰날:
            총액표 = {str(s["날짜"]): PF._숫자(s["총액"]) / 1e8 for s in 스냅}
            fig.add_trace(go.Scatter(
                x=[v["기록일"] for v in 큰날], y=[총액표.get(v["기록일"]) for v in 큰날],
                mode="markers+text", name="큰 변동",
                marker=dict(size=10, color=[색(v["차이"]) for v in 큰날],
                            line=dict(color=카드, width=2)),
                text=[f"{_md(v['날짜'])} {BR.증감(v['차이'])}" for v in 큰날],
                textposition="bottom center",
                textfont=dict(color=[색(v["차이"]) for v in 큰날], size=12),
                hovertemplate="%{text}<extra></extra>"))
        # 축 범위 — 하루만 크게 틀린 원금(예: 10/2 의 8.19억)이 축을 늘려 그래프를
        # 납작하게 만들지 않게, 원금은 중앙값의 ±50% 안쪽 값만 범위에 넣습니다.
        # (자료는 고치지 않습니다. 벗어난 점은 위로 잘려 보입니다)
        원금들 = sorted(p[1] for p in 원금쌍)
        if 원금들:
            가운데 = 원금들[len(원금들) // 2]
            원금들 = [v for v in 원금들 if 0.5 * 가운데 <= v <= 1.5 * 가운데]
        아래, 위 = min(평가 + 원금들), max(평가 + 원금들)
        여유 = (위 - 아래) * 0.08 or 0.01
        fig.update_layout(
            height=340, margin=dict(l=8, r=8, t=8, b=8),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Noto Sans KR, sans-serif", color=흐림),
            legend=dict(orientation="h", y=1.08, x=0, font=dict(color=흐림)),
            xaxis=dict(showgrid=False, tickformat="%-m/%-d", color=흐림,
                       linecolor=테두리),
            yaxis=dict(range=[아래 - 여유, 위 + 여유],
                       gridcolor="rgba(255,255,255,0.05)", ticksuffix="억",
                       tickformat=".2f", color=흐림, zeroline=False),
            hovermode="x unified")
        ui.차트(fig, key="home_추이")
        st.caption(f"아침 브리핑 기록 {len(스냅)}일 · 점은 입출금을 뺀 시장 변동이 하루 "
                   f"±{BR.큰변동_총자산}% 이상인 날")


def 계좌_구성(자):
    오늘 = 자["오늘"]
    계좌 = {k: PF._숫자(v) for k, v in (오늘.get("계좌") or {}).items() if PF._숫자(v) > 0}
    총액 = PF._숫자(오늘["총액"])
    합 = sum(계좌.values())
    with 칸("accounts"):
        st.markdown('<div class="hc-title">계좌 구성</div>', unsafe_allow_html=True)
        if not 계좌:
            st.caption("계좌 기록이 없습니다.")
            return
        차례 = sorted(계좌.items(), key=lambda x: -x[1])
        fig = go.Figure()
        for i, (이름, 금액) in enumerate(차례):
            fig.add_trace(go.Bar(
                x=[금액], y=[""], orientation="h", name=짧은계좌(이름),
                marker=dict(color=회색들[i % len(회색들)]),
                hovertemplate=f"{짧은계좌(이름)} {BR.만원(금액)}<extra></extra>"))
        fig.update_layout(
            barmode="stack", height=46, margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(visible=False), yaxis=dict(visible=False))
        ui.차트(fig, key="home_계좌막대")
        줄 = "".join(
            f'<div class="hc-row"><span><span class="hc-dot" '
            f'style="background:{회색들[i % len(회색들)]}"></span>{짧은계좌(이름)}</span>'
            f'<span>{BR.만원(금액)}<span class="r">{금액 / 합 * 100:.1f}%</span></span></div>'
            for i, (이름, 금액) in enumerate(차례))
        st.markdown(줄, unsafe_allow_html=True)
        # 투자자산 합계 = 계좌별 합계 확인
        if abs(합 - 총액) < 1:
            st.caption(f"계좌 합계 {BR.만원(합)} = 투자자산 합계 ✓")
        else:
            st.markdown(f'<div class="hc-sub" style="color:{주황}">계좌 합계 {BR.만원(합)} ≠ '
                        f'투자자산 합계 {BR.만원(총액)} (차이 {BR.증감(합 - 총액)})</div>',
                        unsafe_allow_html=True)


def 목표_비중(자):
    """일반 계좌 목표 비중 — 기록의 종목 금액을 앱의 자산군과 이어서 셉니다.

    브리핑의 '할 일' 과 같은 계산(목표 × 계좌 합계 - 현재)이지만, 시세를
    새로 받지 않고 오늘 아침 기록의 금액을 씁니다.
    """
    자산 = 자["자산"]
    목표 = {k: float(v) for k, v in (자산.get("목표") or BR.기본_목표비중).items()
          if v not in (None, "")}
    기준 = 자산.get("목표기준") or PF.목표기준_추측(목표)
    대상 = set(BR.리밸런싱_계좌)
    분류 = {}
    for r in 자산.get("종목") or []:
        if not isinstance(r, dict):
            continue
        열쇠 = f"{r.get('계좌')}|{r.get('티커') or r.get('이름')}"
        분류[열쇠] = r.get("시장") if 기준 == "시장" else r.get("자산군")
    현재 = {}
    for 열쇠, 칸값 in ((자["오늘"].get("종목") or {}).items()):
        if str(칸값.get("계좌") or 열쇠.split("|")[0]) not in 대상:
            continue
        묶 = 분류.get(열쇠) or "기타"
        현재[묶] = 현재.get(묶, 0.0) + PF._숫자(칸값.get("금액"))
    전체 = sum(현재.values())
    with 칸("targets"):
        머리, 설명 = st.columns([2, 1])
        머리.markdown(f'<div class="hc-title">{"·".join(대상)} 계좌 목표 비중</div>',
                    unsafe_allow_html=True)
        설명.markdown(f'<div class="hc-sub" style="text-align:right">세로선 = 목표 · '
                    f'{_md(자["날"])} 아침 기록</div>', unsafe_allow_html=True)
        if 전체 <= 0:
            st.caption("종목별 기록이 없습니다 (최근 8일치만 남습니다).")
            return
        이름들 = sorted(set(현재) | set(목표),
                     key=lambda n: -max(현재.get(n, 0) / 전체 * 100, 목표.get(n, 0)))
        눈금 = max([현재.get(n, 0) / 전체 * 100 for n in 이름들]
                 + list(목표.values()) + [10]) * 1.15
        줄, 안쪽 = [], []
        for n in 이름들:
            지금 = 현재.get(n, 0.0) / 전체 * 100
            목 = 목표.get(n)
            넘음 = 목 is not None and abs(지금 - 목) >= BR.리밸런싱_괴리
            조정 = (목 / 100 * 전체 - 현재.get(n, 0.0)) if 목 is not None else None
            막대색 = 주황 if 넘음 else 회색들[3]
            목표글 = f" / 목표 {목:.0f}%" if 목 is not None else " / 목표 없음"
            html = (f'<div class="hc-item"><span>{n}</span><span><b>{지금:.0f}%</b>'
                    f'<span style="color:{흐림}">{목표글}</span></span></div>'
                    f'<div class="hc-bar"><div class="fill" style="width:{지금 / 눈금 * 100:.1f}%;'
                    f'background:{막대색}"></div>'
                    + (f'<div class="goal" style="left:{목 / 눈금 * 100:.1f}%"></div>'
                       if 목 is not None else "") + '</div>')
            if 넘음:
                말 = "더 사기" if 조정 > 0 else "줄이기"
                html += (f'<div class="hc-sub" style="color:{주황}">{지금 - 목:+.0f}%p '
                         f'{"초과" if 지금 > 목 else "부족"} · {BR.만원(조정)} {말}</div>')
            elif 조정 is not None and BR.만원(조정) != "0":
                안쪽.append((n, 조정))
            줄.append(html)
        st.markdown("".join(줄), unsafe_allow_html=True)
        if 안쪽:
            합 = sum(v for _, v in 안쪽)
            안쪽.sort(key=lambda x: -abs(x[1]))
            st.markdown(f'<div class="hc-sub" style="margin-top:.7rem">그 외 항목 합계 '
                        f'{BR.증감(합)} ({BR.리밸런싱_괴리:.0f}%p 이내: '
                        + ", ".join(f"{n} {BR.증감(v)}" for n, v in 안쪽) + ")</div>",
                        unsafe_allow_html=True)
        if abs(sum(목표.values()) - 100) > 0.5:
            st.markdown(f'<div class="hc-sub" style="color:{주황}">목표 비중 합이 '
                        f'{sum(목표.values()):.0f}% 입니다 — 자산배분에서 100% 로 맞추세요</div>',
                        unsafe_allow_html=True)


def 보유_종목(자):
    오늘, 주초 = 자["오늘"], 자["주초"]
    종목 = 오늘.get("종목") or {}
    with 칸("holdings"):
        머리, 설명 = st.columns([2, 1])
        머리.markdown('<div class="hc-title">보유 종목</div>', unsafe_allow_html=True)
        설명.markdown('<div class="hc-sub" style="text-align:right">열 제목을 눌러 정렬</div>',
                    unsafe_allow_html=True)
        if not 종목:
            st.caption("종목별 기록이 없습니다 (최근 8일치만 남습니다).")
            return
        주간 = {}
        if 주초.get("종목"):
            for r in PF.종목_움직임(오늘, 주초)["목록"]:
                주간[(r["이름"], r["계좌"])] = r["시장분"]
        행 = []
        for 열쇠, v in 종목.items():
            계좌 = str(v.get("계좌") or 열쇠.split("|")[0])
            금액, 원금 = PF._숫자(v.get("금액")), PF._숫자(v.get("원금"))
            행.append({"종목": str(v.get("이름") or 열쇠), "계좌": 짧은계좌(계좌),
                      "평가액": round(금액),
                      "수익률": ((금액 - 원금) / 원금 * 100) if 원금 > 0 else None,
                      "이번 주": (round(주간.get((str(v.get("이름") or 열쇠), 계좌), 0))
                                if 주초.get("종목") else None)})
        표 = pd.DataFrame(행).sort_values("평가액", ascending=False)

        def 칠하기(v):
            if v is None or pd.isna(v) or v == 0:
                return f"color:{흐림}"
            return f"color:{빨강 if v > 0 else 파랑}"
        모양 = (표.style.map(칠하기, subset=["수익률", "이번 주"])
              .format({"평가액": "{:,.0f}", "수익률": "{:+.1f}%", "이번 주": "{:+,.0f}"},
                      na_rep="-"))
        st.dataframe(모양, hide_index=True, width="stretch",
                     height=min(38 * (len(표) + 1) + 4, 460))
        st.caption("평가액·이번 주는 원 · 이번 주 = 입출금을 뺀 시세 변동 "
                   + (f"(vs {_md(주초['날짜'])})" if 주초 else "(이번 주 기록 없음)"))


def 환율_카드(자, 키):
    """달러는 기록의 환율, 엔은 외화 보유 평가로 역산. 싼 구간 진입일 포함."""
    오늘 = 자["오늘"]
    위치 = (오늘.get("환율위치") or {})
    조각 = []
    달러 = PF._숫자(오늘.get("환율"))
    엔칸 = (오늘.get("종목") or {}).get("외화|JPY") or {}
    엔 = (PF._숫자(엔칸.get("금액")) / PF._숫자(엔칸.get("수량")) * 100
         if PF._숫자(엔칸.get("수량")) > 0 else None)
    if 엔:
        조각.append(f"엔 {엔:,.0f}")
    통화 = "미국 달러 (USD)"
    p = 위치.get(통화)
    구간 = BR._구간말(p)
    날수 = PF.기록_구간날수(자["스냅"], 통화, 자["날"], p, BR.환율_싼구간, BR.환율_비싼구간)
    if 날수 >= 1 and 구간:
        진입 = date.fromisoformat(자["날"]) - timedelta(days=날수 - 1)
        조각.append(f"{_md(진입)}부터 {날수}일째")
    제목 = f"환율 ({구간})" if 구간 else "환율"
    아래 = " · ".join(조각) or (_md(자["날"]) + " 아침 기록")
    with 칸(키):
        st.markdown(f'<div class="hc-label">{제목}</div>'
                    f'<div class="hc-mid">달러 {달러:,.0f}원</div>'
                    f'<div class="hc-sub">{아래}</div>', unsafe_allow_html=True)


def 금리_카드(키, 한, 미):
    with 칸(키):
        st.markdown('<div class="hc-label">기준금리</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        for col, x, 이름 in ((a, 한, "한국"), (b, 미, "미국")):
            col.markdown(f'<div class="hc-mid">{x["값"] if x else "-"}</div>'
                         f'<div class="hc-sub">{이름}</div>', unsafe_allow_html=True)
        기준 = (한 or 미 or {}).get("기준")
        if 기준:
            st.markdown(f'<div class="hc-sub">{기준} 기준</div>', unsafe_allow_html=True)


def 작은_카드(키, 이름, 값, 아래, 아래색=None):
    with 칸(키):
        st.markdown(f'<div class="hc-label">{이름}</div><div class="hc-mid">{값}</div>'
                    f'<div class="hc-sub" style="color:{아래색 or 흐림}">{아래}</div>',
                    unsafe_allow_html=True)


# ==========================================================================
# 그리기
# ==========================================================================
손님 = storage.손님인가()
자 = None if 손님 else _안전("투자자산", 투자자료)

with st.container(key="hwrap"):
    머리 = "개인 대시보드"
    st.title(머리)
    if 자:
        첫날 = 자["스냅"][0]["날짜"]
        st.caption(f"{_요일(자['날'])} 기준 · 추적 시작 {_md(첫날)}")
    storage.임시서버_안내()
    if 손님:
        st.info("Guest 모드에서는 저장된 자료를 불러오지 않습니다. "
                "요약 대신 프로그램 목록만 보여드립니다.", icon="👤")
    ui.페이지_메뉴(__file__)

    if not 손님:
        한 = _안전("금리(한국)", lambda: 금리_요약("KR"))
        미 = _안전("금리(미국)", lambda: 금리_요약("US"))
        탭_투자, 탭_시장, 탭_계산 = st.tabs(["투자자산", "시장", "계산기"])

        with 탭_투자:
            if not 자:
                st.info("아침 브리핑 기록이 아직 없습니다. 자산배분에 종목을 저장하고 "
                        "브리핑이 한 번 돌면 여기에 나타납니다.", icon="📝")
            else:
                요약_카드(자)
                추이_차트(자)
                왼, 오 = st.columns(2)
                with 왼:
                    계좌_구성(자)
                with 오:
                    목표_비중(자)
                보유_종목(자)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                금리_카드("rate", 한, 미)
            with c2:
                if 자:
                    환율_카드(자, "fx")
                else:
                    작은_카드("fx", "환율", "-", "브리핑 기록이 쌓이면 나옵니다")
            with c3:
                대출 = _안전("대출", 대출_요약)
                작은_카드("loan", "대출 잔액", 대출["값"] if 대출 else "-",
                       대출["해석"] if 대출 else "대출 계산기에서 저장하면 나옵니다")
            with c4:
                순 = _안전("순자산", 순자산_요약)
                if 순:
                    묵음 = 순["묵음"] >= 30
                    작은_카드("nw", 순["이름"], 순["값"],
                           f"{_md(순['기준날'])} 기준" + (" · 갱신 필요" if 묵음 else ""),
                           주황 if 묵음 else None)
                else:
                    작은_카드("nw", "순자산", "-", "순자산에서 기록을 남기면 나옵니다")

        with 탭_시장:
            a, b, c = st.columns(3)
            for col, x in ((a, 한), (b, 미)):
                with col:
                    if x:
                        작은_지표(x)
            with c:
                if 자:
                    환율_카드(자, "fx_m")
            st.page_link("pages/5_🥚_금리_사이클.py", label="금리 사이클 자세히")
            st.page_link("pages/2_💱_환전_타이밍.py", label="환전 타이밍 자세히")

        with 탭_계산:
            카드들 = [x for x in (_안전("연봉", 연봉_요약), _안전("재산세", 재산세_요약),
                              _안전("양도세", 양도세_요약)) if x]
            if 카드들:
                for col, x in zip(st.columns(3), 카드들):
                    with col:
                        작은_지표(x)
            else:
                st.info("연봉·부동산 세금 계산기에서 저장하면 여기에 요약이 나옵니다.", icon="📝")
            st.page_link("pages/4_💰_연봉_급여_관리.py", label="연봉 자세히")
            st.page_link("pages/3_🏠_부동산_세금.py", label="부동산 세금 자세히")
            st.page_link("pages/1_🏦_대출_상환_계산기.py", label="대출 상환 자세히")

        if 문제:
            with st.expander("요약을 만들지 못한 항목"):
                for m in 문제:
                    st.text("  " + m)
                st.caption("해당 페이지에서 설정을 저장하면 여기에 나타납니다.")

    # ======================================================================
    # 전체 프로그램 목록 — 휴대폰에서 사이드바를 못 열 때 다른 묶음으로 가는 길
    # ======================================================================
    st.divider()
    st.markdown('<div class="묶음제목">전체 프로그램</div>', unsafe_allow_html=True)
    내프로그램 = addons.정상_목록()
    for i, (col, (묶음이름, 페이지들)) in enumerate(zip(st.columns(len(ui.메뉴묶음)),
                                                     ui.메뉴묶음)):
        with col, st.container(border=True, key=f"homebox_{i}_{묶음이름[-2:]}"):
            st.markdown(f"**{글자만(묶음이름)}**")
            for 경로, 아이콘, 이름, 설명 in 페이지들:
                if ui._있나(경로):
                    st.page_link(경로, label=이름, help=설명 or None)
            if 묶음이름.endswith("도구") and 내프로그램:
                st.caption("myapps/ — " + " · ".join(p["제목"] for p in 내프로그램))

    with st.expander("사용 / 관리 안내"):
        아이콘, 짧게, 자세히 = storage.저장소_상태()
        st.markdown(
            f"**저장 위치** — {아이콘} {짧게}. {자세히}\n\n"
            "**투자자산 숫자** — 아침 브리핑이 매일 남기는 기록을 씁니다. "
            "텔레그램과 같은 기준이라 숫자가 같습니다.\n\n"
            "**요약이 안 보이는 항목** — 그 프로그램에서 설정을 한 번 저장하면 "
            "여기에 나타납니다.\n\n"
            "**외부 접속** — `외부접속_설정_가이드.md` 참고"
        )
