"""
==========================================================================
개인 대시보드 - 첫 화면
==========================================================================
각 프로그램의 요약을 한눈에 보여줍니다.

[설계 원칙]
 · 첫 화면은 빨라야 합니다. 그래서 **저장된 자료로 계산만 하고**
   시세·환율 같은 네트워크 조회는 하지 않습니다.
   (대출 상환표, 재산세, 연봉, 양도세는 모두 오프라인 계산입니다)
 · 시세가 필요한 것(환전·자산배분·금리)은 각 페이지를 한 번 열면
   그 세션 동안 캐시가 살아 있어서 여기서도 즉시 보입니다.
   캐시가 없으면 "열어보세요" 라고만 안내합니다.
 · 저장된 자료가 없는 프로그램은 카드만 보여줍니다.
==========================================================================
"""

import os
import sys
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import addons  # noqa: E402
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402

require_login(page_title="개인 대시보드", page_icon="🗂️", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

st.title("🗂️ 개인 대시보드")
storage.임시서버_안내()

손님 = storage.손님인가()
if 손님:
    st.info("👤 Guest 모드에서는 저장된 자료를 불러오지 않습니다. "
            "요약 대신 프로그램 목록만 보여드립니다.", icon="👤")

ui.페이지_메뉴(__file__)

# ==========================================================================
# 요약 모으기 (네트워크 없이, 저장된 자료로만)
# ==========================================================================
요약들 = []
문제 = []


def _안전(이름, 함수):
    """한 프로그램의 요약이 실패해도 나머지는 보이게 합니다."""
    try:
        결과 = 함수()
        if 결과:
            요약들.append(결과)
    except Exception as e:  # noqa: BLE001
        문제.append(f"{이름}: {type(e).__name__}")


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
    오늘 = date.today()
    남은 = [r for r in 결과 if r["날짜"] >= 오늘 and r["구분"] == "정기납입"]
    잔액 = 남은[0]["잔액"] if 남은 else 0
    월납 = 남은[0]["납입액"] if 남은 else 0
    return {
        "이름": "🏦 대출", "경로": "pages/1_🏦_대출_상환_계산기.py",
        "핵심": ui.억(잔액), "부제": f"남은 {len(남은)}회 · 월 {월납 / 1e4:,.0f}만",
        "그래프": ("잔액", [(r["날짜"], r["잔액"]) for r in 결과
                       if r["구분"] == "정기납입"][::3]),
        "덧말": f"총이자 {ui.억(s['총이자'])} · 완납 {s['완납일']}",
    }


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
    기록 = 자료.get("history") or []
    return {
        "이름": "🏠 재산세·종부세", "경로": "pages/3_🏠_재산세_종부세.py",
        "핵심": ui.원(연간), "부제": f"부동산 {len(목록)}건",
        "막대": [("7월", r.july_total), ("9월", r.sep_total), ("12월", r.j_total)],
        "덧말": (f"연도별 기록 {len(기록)}개" if 기록 else "연도별 기록을 남겨보세요"),
    }


def 연봉_요약():
    자료 = storage.불러오기("salary", None)
    if not 자료:
        return None
    from engines import salary as S
    기록 = S.dashboard_records(자료)
    if not 기록:
        return None
    최근 = 기록[-1]
    목표, 목표율 = S.recommended_salary(기록)
    return {
        "이름": "💰 연봉", "경로": "pages/4_💰_연봉_급여_관리.py",
        "핵심": ui.원(최근["base_sal"]), "부제": f"{최근['year']}년 기준",
        "그래프": ("연봉", [(date(r["year"], 12, 31), r["base_sal"]) for r in 기록]),
        "덧말": ((f"인상률 {최근['raise']:+.2f}%" if 최근["raise"] is not None
                else "비교 기준 없음")
              + (f" · 내년 권장 {ui.억(목표)}" if 목표 else "")),
    }


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
    return {
        "이름": "🏷️ 양도세", "경로": "pages/6_🏷️_양도세_계산기.py",
        "핵심": ("비과세" if r.비과세인가 else ui.억(r.총세액)),
        "부제": f"양도가 {ui.억(입력.양도가액)} 기준",
        "막대": ([] if r.비과세인가
               else [("실수령", r.실수령액), ("세금", r.총세액)]),
        "덧말": (r.비과세사유[:40] if r.비과세인가
              else f"차익의 {r.유효세율:.1f}% · 실수령 {ui.억(r.실수령액)}"),
    }


def 금리_요약():
    from engines import egg_cycle as EC
    설정 = storage.불러오기("egg_cycle", {}) or {}
    나라 = 설정.get("country", "KR")
    이력, 출처, _오류 = EC.이력_불러오기(나라, None, ())
    수동 = 설정.get("manual_rate")
    if 수동:
        이력 = EC.RateHistory(list(이력.points) + [(date.today(), float(수동))]).sort()
    상태 = EC.compute_state(이력, EC.CycleConfig(
        country=나라, cycle_low=설정.get("cycle_low"),
        cycle_high=설정.get("cycle_high"),
        lookback_years=int(설정.get("lookback_years", 3))), 출처)
    날짜, 값 = 이력.계단_시계열()
    return {
        "이름": "🥚 금리 사이클", "경로": "pages/5_🥚_금리_사이클.py",
        "핵심": f"{상태.rate:.2f}%", "부제": f"{상태.phase.name} · {상태.phase.regime}",
        "그래프": ("기준금리", list(zip(날짜, 값))),
        "덧말": f"사이클 {상태.r * 100:.0f}% · {상태.phase.action}",
    }


def 자산배분_요약():
    자료 = storage.불러오기("portfolio", None)
    if not 자료 or not 자료.get("종목"):
        return None
    from engines import portfolio as PF
    수동만 = [x for x in 자료["종목"]
            if x.get("현재가(수동)") or x.get("평가액(직접입력)")]
    if not 수동만:
        return {
            "이름": "📊 자산배분", "경로": "pages/7_📊_자산배분.py",
            "핵심": f"{len(자료['종목'])}종목",
            "부제": "시세를 받아야 평가액이 나옵니다",
            "덧말": "페이지를 열면 시세를 조회합니다",
        }
    종목들 = [PF.종목_계산(x, None, 1390.0) for x in 수동만]
    s = PF.요약(종목들)
    묶 = PF.집계(종목들, "자산군")
    return {
        "이름": "📊 자산배분", "경로": "pages/7_📊_자산배분.py",
        "핵심": ui.억(s["평가액"]) + " 이상",
        "부제": f"수동 입력분 {len(수동만)}/{len(자료['종목'])}종목만",
        "도넛": [(g["이름"], g["평가액"]) for g in 묶],
        "덧말": "정확한 값은 페이지를 열어 시세를 받아보세요",
    }


if not 손님:
    with st.spinner("저장된 자료로 요약을 만드는 중이에요..."):
        for 이름, 함수 in [("대출", 대출_요약), ("자산배분", 자산배분_요약),
                        ("금리", 금리_요약), ("재산세", 재산세_요약),
                        ("연봉", 연봉_요약), ("양도세", 양도세_요약)]:
            _안전(이름, 함수)

# ==========================================================================
# 요약 그리기
# ==========================================================================
if 요약들:
    st.caption("저장된 자료로 계산한 요약입니다. 카드를 누르면 해당 프로그램으로 갑니다.")
    for i in range(0, len(요약들), 2):
        묶음 = 요약들[i:i + 2]
        cols = st.columns(len(묶음))
        for col, item in zip(cols, 묶음):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{item['이름']}**")
                    st.markdown(f"### {item['핵심']}")
                    st.caption(item.get("부제", ""))

                    if item.get("그래프"):
                        라벨, 점들 = item["그래프"]
                        if 점들:
                            fig = go.Figure(go.Scatter(
                                x=[p[0] for p in 점들], y=[p[1] for p in 점들],
                                mode="lines", line=dict(color="#2B6ED5", width=2),
                                fill="tozeroy",
                                fillcolor="rgba(43,110,213,.12)",
                                hovertemplate="%{x|%Y-%m}<br>%{y:,.0f}<extra></extra>"))
                            fig.update_layout(
                                height=110, margin=dict(l=0, r=0, t=4, b=0),
                                xaxis=dict(visible=False), yaxis=dict(visible=False),
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
                            st.plotly_chart(fig, width="stretch",
                                            key=f"g_{item['이름']}")

                    if item.get("막대"):
                        fig = go.Figure(go.Bar(
                            x=[b[0] for b in item["막대"]],
                            y=[b[1] for b in item["막대"]],
                            marker_color="#18A57A",
                            hovertemplate="%{x}<br>%{y:,.0f}원<extra></extra>"))
                        fig.update_layout(
                            height=110, margin=dict(l=0, r=0, t=4, b=0),
                            yaxis=dict(visible=False),
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
                        st.plotly_chart(fig, width="stretch",
                                        key=f"b_{item['이름']}")

                    if item.get("도넛"):
                        fig = go.Figure(go.Pie(
                            labels=[d[0] for d in item["도넛"]],
                            values=[d[1] for d in item["도넛"]], hole=0.6,
                            textinfo="none",
                            marker=dict(colors=["#2B6ED5", "#18A57A", "#E28A2B",
                                                "#C0392B", "#8E7CC3", "#3B7EA1"]),
                            hovertemplate="%{label} %{percent}<extra></extra>"))
                        fig.update_layout(
                            height=110, margin=dict(l=0, r=0, t=4, b=0),
                            showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig, width="stretch",
                                        key=f"p_{item['이름']}")

                    st.caption(item.get("덧말", ""))
                    st.page_link(item["경로"], label="자세히 보기", icon="➡️")

    if 문제:
        with st.expander("요약을 만들지 못한 항목"):
            for m in 문제:
                st.text("  " + m)
            st.caption("해당 페이지에서 설정을 저장하면 여기에 나타납니다.")
elif not 손님:
    st.info("아직 저장된 자료가 없습니다. 아래 프로그램에서 설정을 저장하면 "
            "여기에 요약이 나타납니다.", icon="📝")

# ==========================================================================
# 전체 프로그램 목록
# ==========================================================================
st.divider()
st.subheader("전체 프로그램")

프로그램 = [
    ("🏦", "대출 상환 계산기", "고정→변동금리, 날짜 기준 중도상환, 중도상환수수료",
     "pages/1_🏦_대출_상환_계산기.py"),
    ("💱", "환전 타이밍", "달러·엔·유로·위안·싱달러의 기간별 평균 대비 현재 환율",
     "pages/2_💱_환전_타이밍.py"),
    ("🏠", "재산세 · 종합부동산세", "공시가격·지분으로 7월/9월 재산세와 12월 종부세",
     "pages/3_🏠_재산세_종부세.py"),
    ("💰", "연봉 · 급여 관리", "연도별 연봉, 물가 대비 실질 인상률, 내년 권장 연봉",
     "pages/4_💰_연봉_급여_관리.py"),
    ("🥚", "금리 사이클", "달걀 모형으로 보는 기준금리 위치 · FOMC 확률",
     "pages/5_🥚_금리_사이클.py"),
    ("🏷️", "양도세 계산기", "보유기간·주택수로 예상 양도소득세, 세제개편안 비교",
     "pages/6_🏷️_양도세_계산기.py"),
    ("📊", "자산배분 현황", "주식·ETF·펀드·코인을 계좌별로 · 금리 국면과 대조",
     "pages/7_📊_자산배분.py"),
    ("📥", "자료 가져오기", "예전 프로그램에서 저장한 JSON 파일 올리기",
     "pages/8_📥_자료_가져오기.py"),
]

for 아이콘, 이름, 설명, 경로 in 프로그램:
    with st.container(border=True):
        st.markdown(f"**{아이콘} {이름}**")
        st.caption(설명)
        st.page_link(경로, label=f"{이름} 열기", icon="➡️")

내프로그램 = addons.정상_목록()
with st.container(border=True):
    st.markdown("**➕ 내 프로그램**")
    if 내프로그램:
        st.caption("`myapps/` 에서 찾은 프로그램 "
                   + " · ".join(f"{p['아이콘']} {p['제목']}" for p in 내프로그램))
    else:
        st.caption("`myapps/` 폴더에 .py 파일을 넣으면 여기에 자동으로 나타납니다.")
    st.page_link("pages/9_➕_내_프로그램.py", label="내 프로그램 열기", icon="➡️")

st.divider()
with st.expander("ℹ️ 사용 / 관리 안내"):
    아이콘, 짧게, 자세히 = storage.저장소_상태()
    st.markdown(
        f"**저장 위치** — {아이콘} {짧게}. {자세히}\n\n"
        "**요약이 안 보이는 항목** — 그 프로그램에서 설정을 한 번 저장하면 "
        "여기에 나타납니다. 환전·자산배분처럼 시세가 필요한 것은 해당 페이지를 "
        "한 번 열어야 정확한 값이 나옵니다.\n\n"
        "**화면 테마** — PC·휴대폰의 다크모드 설정을 따라갑니다. "
        "직접 고르려면 우측 상단 ⋮ → Settings → Appearance.\n\n"
        "**외부 접속** — `외부접속_설정_가이드.md` 참고"
    )
