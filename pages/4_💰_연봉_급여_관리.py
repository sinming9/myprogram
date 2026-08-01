import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import salary as S  # noqa: E402

require_login(page_title="연봉·급여 관리", page_icon="💰", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("💰 연봉 · 급여 관리")
st.caption("기록하고, 비교하고, 내 연봉의 실질 가치를 확인하세요.")

# ※ 두 키를 각각 setdefault 로 초기화합니다.
#   예전처럼 "급여_자료 가 없을 때만" 안쪽에서 급여_표버전 을 만들면,
#   다른 페이지(자료 가져오기 등)가 급여_자료 만 넣어준 경우
#   급여_표버전 이 없어서 KeyError 가 납니다.
st.session_state.setdefault("급여_자료", storage.불러오기("salary", {}) or {})
st.session_state.setdefault("급여_표버전", 0)

자료 = st.session_state["급여_자료"]

storage.임시서버_안내()
def _복원후(데이터):
    st.session_state["급여_자료"] = 데이터
    st.session_state["급여_표버전"] = st.session_state.get("급여_표버전", 0) + 1


storage.백업_사이드바("salary", 자료, "연봉자료_백업", 복원_콜백=_복원후)
st.sidebar.page_link("pages/8_📥_자료_가져오기.py", label="예전 자료 올리기", icon="📥")

# ==========================================================================
# 연도 선택  (본문 맨 위에 크게 배치)
#   예전에는 사이드바에만 있어서, 사이드바가 접히는 휴대폰에서는 연도를 바꿀
#   방법이 화면에 보이지 않았습니다. 그래서 늘 기본 연도만 입력하게 됐습니다.
#   또 selectbox 에 key 없이 index 를 계산해서 넘기면, index 가 바뀔 때마다
#   Streamlit 이 다른 위젯으로 보고 선택을 초기화합니다. key 로 고정했습니다.
# ==========================================================================
입력된연도 = sorted(int(y) for y in 자료 if str(y).isdigit())


def _자료있음(연: int) -> bool:
    return S.base_salary_for_calc(자료, 연) > 0


if "급여_연도" not in st.session_state:
    st.session_state["급여_연도"] = (입력된연도[-1] if 입력된연도 and 입력된연도[-1] in S.YEARS
                                else (2026 if 2026 in S.YEARS else S.YEARS[-1]))

# 이전/다음 버튼이 남긴 요청을 위젯 만들기 "전에" 반영 (Streamlit 규칙)
if "_연도이동" in st.session_state:
    st.session_state["급여_연도"] = st.session_state.pop("_연도이동")

전, 가운데, 다음 = st.columns([1, 4, 1])
연도 = 가운데.selectbox(
    "연도 선택", S.YEARS, key="급여_연도",
    format_func=lambda y: f"{y}년" + ("  ✓" if _자료있음(y) else ""),
    help="✓ 표시는 이미 자료가 들어있는 연도입니다",
)
if 전.button("◀", width="stretch", help="이전 연도"):
    st.session_state["_연도이동"] = max(S.YEARS[0], 연도 - 1)
    st.rerun()
if 다음.button("▶", width="stretch", help="다음 연도"):
    st.session_state["_연도이동"] = min(S.YEARS[-1], 연도 + 1)
    st.rerun()

if 입력된연도:
    st.caption("자료가 있는 연도: " + " · ".join(
        f"**{y}**" if _자료있음(y) else f"{y}(빈칸)" for y in 입력된연도))
else:
    st.caption("아직 입력된 연도가 없습니다. 아래 **✍️ 급여 입력** 탭에서 시작하세요. "
               "예전에 쓰던 `salary_data.json` 이 있으면 "
               "**📥 자료 가져오기** 페이지에서 한 번에 올릴 수 있습니다.")

기록들 = S.dashboard_records(자료)

탭1, 탭2, 탭3 = st.tabs(["📊 대시보드", "📅 연도별 현황", "✍️ 급여 입력"])

# ==========================================================================
# 대시보드
# ==========================================================================
with 탭1:
    if not 기록들:
        st.info("아직 자료가 없습니다. **✍️ 급여 입력** 탭에서 연봉을 입력해 보세요.", icon="📝")
    else:
        최근 = 기록들[-1]
        목표, 목표율 = S.recommended_salary(기록들)
        추세, 물가목표, 근거 = S.recommendation_basis(기록들)

        ui.카드_줄([
            (f"{최근['year']}년 기본(계약) 연봉", S.money(최근["base_sal"]), ""),
            ("최근 세후 수령액", S.money(최근["net"]) if 최근["net"] else "입력 필요", ""),
            ("최근 명목 인상률",
             f"{최근['raise']:+.2f}%" if 최근["raise"] is not None else "비교 기준 없음", ""),
            (f"{최근['year'] + 1}년 권장 계약연봉",
             S.money(목표) if 목표 else "계산 기준 없음", f"{목표율:.2f}% 적용" if 목표율 else ""),
        ], 열수=2)

        st.caption(
            f"권장 연봉 계산 기준: 최근 기본/계약 연봉 × (1 + {목표율:.2f}%). "
            f"최근 3년 평균 인상률 {추세:.2f}% 와 평균 물가상승률+2% ({물가목표:.2f}%) 중 "
            f"**{근거}**을 적용했습니다."
        )

        st.divider()
        총세전 = sum(r["gross"] for r in 기록들)
        총세후 = sum(r["net"] for r in 기록들)
        총상여 = sum(r["bonus"] for r in 기록들)
        실질누적 = S.inflation_adjusted_total(자료, 기록들)
        ui.카드_줄([
            ("누적 세전 총액", S.money(총세전), f"{len(기록들)}개 연도"),
            ("누적 세후 수령액", S.money(총세후) if 총세후 else "입력 필요", ""),
            ("누적 상여금", S.money(총상여) if 총상여 else "-", ""),
            (f"{최근['year']}년 물가 기준 실질 누적", S.money(실질누적),
             f"명목 대비 {실질누적 - 총세전:+,}원"),
        ], 열수=2)

        st.divider()
        st.markdown("##### 세전 연봉 · 세후 수령액 추이")
        연도들 = [str(r["year"]) for r in 기록들]
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=연도들, y=[r["gross"] for r in 기록들], name="세전 연봉",
                              marker_color="#2B6ED5"))
        세후값 = [r["net"] if r["net"] else None for r in 기록들]
        if any(v is not None for v in 세후값):
            fig1.add_trace(go.Scatter(x=연도들, y=세후값, name="세후 수령액", mode="lines+markers",
                                      line=dict(color="#18A57A", width=2)))
        fig1.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                           yaxis_title="원", legend=dict(orientation="h", y=1.18),
                           hovermode="x unified")
        st.plotly_chart(fig1, width="stretch")

        st.markdown("##### 인상률과 물가상승률 비교")
        비교 = [r for r in 기록들 if r["raise"] is not None]
        if not 비교:
            st.caption("2개 연도의 연봉을 입력하면 비교가 표시됩니다.")
        else:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=[str(r["year"]) for r in 비교], y=[r["raise"] for r in 비교],
                name="명목 인상률",
                marker_color=["#2B6ED5" if r["raise"] >= 0 else "#D35A5A" for r in 비교]))
            물가값 = [r["inflation"] for r in 비교]
            if any(v is not None for v in 물가값):
                fig2.add_trace(go.Scatter(x=[str(r["year"]) for r in 비교], y=물가값,
                                          name="물가상승률", mode="lines+markers",
                                          line=dict(color="#E28A2B", width=2)))
            fig2.add_hline(y=0, line_color="#AAB7C8")
            fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                               yaxis_title="%", legend=dict(orientation="h", y=1.18),
                               hovermode="x unified")
            st.plotly_chart(fig2, width="stretch")

# ==========================================================================
# 연도별 현황
# ==========================================================================
with 탭2:
    행들 = S.연도별_표(자료)
    if not 행들:
        st.info("아직 자료가 없습니다.", icon="📝")
    else:
        평가, 설명, 명목, 실질 = S.연도_평가(자료, 연도)
        세전, 세후, 상여, 계약 = S.totals(자료, 연도)
        기준연봉 = S.base_salary_for_calc(자료, 연도)
        기록 = S.get_year_data(자료, 연도)

        with st.container(border=True):
            st.markdown(f"##### {연도}년 한눈에 보기")
            줄 = []
            if 계약:
                줄.append(f"계약 연봉 **{S.money(계약)}**")
            줄.append(f"실제 세전 **{S.money(세전) if 세전 else '-'}**")
            if 계약 and 세전:
                차 = 세전 - 계약
                줄.append(f"수당/상여 차액 **{'+' if 차 >= 0 else '−'}{S.money(abs(차))}**")
            줄.append(f"세후 수령액 **{S.money(세후) if 세후 else '-'}**")
            줄.append(f"상여금 **{S.money(상여) if 상여 else '-'}**")
            if 기록.get("inflation"):
                줄.append(f"물가상승률 **{기록['inflation']}%**")
            st.markdown(" · ".join(줄))

            이전기록 = [r for r in 기록들 if r["year"] < 연도]
            예상, 예상율 = S.recommended_salary(이전기록)
            if 예상:
                차이 = (기준연봉 - 예상) if 기준연봉 else None
                문구 = f"이 해의 예상(권장) 연봉: **{S.money(예상)}** ({예상율:.2f}% 적용)"
                if 차이 is not None:
                    문구 += f" · 실제와 {S.money(abs(차이))} {'높음' if 차이 >= 0 else '낮음'}"
                st.caption(문구)

            색 = S.평가_색상.get(평가, "#666")
            st.markdown(f"평가: <span style='color:{색};font-weight:700'>{평가}</span> — {설명}",
                        unsafe_allow_html=True)
            if 기록.get("note"):
                st.caption(f"메모: {기록['note']}")

        표df = pd.DataFrame(행들)
        st.dataframe(
            표df.style.format({
                "계약 연봉": "{:,.0f}", "실제 세전": "{:,.0f}", "예상 연봉": "{:,.0f}",
                "세후 수령액": "{:,.0f}", "상여금": "{:,.0f}",
                "물가상승률(%)": "{:.1f}", "명목 인상률(%)": "{:+.2f}",
                "물가 반영 변화(%)": "{:+.2f}",
            }, na_rep="-"),
            width="stretch", hide_index=True, height=380,
        )
        st.download_button(
            "📄 CSV 내려받기", data=표df.to_csv(index=False).encode("utf-8-sig"),
            file_name="연봉기록.csv", mime="text/csv", width="stretch")
        st.caption(
            "예상 연봉 = 직전 기록까지의 최근 3년 평균 인상률과 (최근 3년 평균 물가상승률 + 2%) 중 "
            "높은 값을 계약 연봉(우선)에 적용한 목표입니다."
        )
        st.caption(
            "평가 기준: 물가 반영 변화 +2%p 이상 '매우 양호' · 0% 이상 '물가 방어' · "
            "0% 미만 '실질 하락'. 물가 반영 변화 = (1 + 명목 인상률) ÷ (1 + 물가상승률) − 1"
        )

# ==========================================================================
# 급여 입력
# ==========================================================================
with 탭3:
    st.markdown(f"##### {연도}년 자료 입력")
    st.caption("다른 연도를 입력하려면 **화면 맨 위의 연도 선택**(◀ ▶ 버튼)을 바꾸세요. "
               "금액은 `1,000,000` / `100만` / `0.01억` / `125000 + 80000` 형태로 모두 됩니다.")

    기록 = S.get_year_data(자료, 연도)
    월들 = 기록.get("months", [])

    c1, c2 = st.columns(2)
    계약입력 = c1.text_input("계약서 연봉", value=f"{int(기록.get('contract_annual', 0) or 0):,}"
                        if 기록.get("contract_annual") else "",
                        help="계약서 기준 순수 계약 연봉", key=f"계약_{연도}_{st.session_state.get('급여_표버전', 0)}")
    세전입력 = c2.text_input("실제 세전 연봉", value=f"{int(기록.get('annual_gross', 0) or 0):,}"
                        if 기록.get("annual_gross") else "",
                        help="아래 월별 합계를 쓸 거면 비워둬도 됩니다", key=f"세전_{연도}_{st.session_state.get('급여_표버전', 0)}")

    c3, c4 = st.columns([1, 2])
    기본물가 = str(기록.get("inflation", "") or "")
    if not 기본물가 and 연도 in S.KOREA_CPI:
        기본물가 = str(S.KOREA_CPI[연도])
    물가입력 = c3.text_input("물가상승률 (%)", value=기본물가,
                        help=f"{연도}년 참고값: {S.KOREA_CPI.get(연도, '자료 없음')}",
                        key=f"물가_{연도}_{st.session_state.get('급여_표버전', 0)}")
    메모입력 = c4.text_input("메모", value=기록.get("note", ""), placeholder="예: 승진, 직급 변경",
                         key=f"메모_{연도}_{st.session_state.get('급여_표버전', 0)}")

    def _칸(값):
        return f"{int(값):,}" if 값 else ""

    행목록 = []
    for i, m in enumerate(S.MONTHS):
        원본 = 월들[i] if i < len(월들) else {}
        행목록.append({
            "월": m,
            "월 급여(세전)": _칸(S.월_표시_급여(원본)),
            "상여금(세전)": _칸(int(원본.get("bonus", 0) or 0)),
            "세금·공제": _칸(S.month_tax(원본)),
            "비고": 원본.get("note", ""),
        })
    월df = pd.DataFrame(행목록)

    편집df = st.data_editor(
        월df,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=f"월별_editor_{연도}_{st.session_state.get('급여_표버전', 0)}",
        column_config={
            "월": st.column_config.NumberColumn(disabled=True, width="small"),
            "월 급여(세전)": st.column_config.TextColumn(),
            "상여금(세전)": st.column_config.TextColumn(),
            "세금·공제": st.column_config.TextColumn(help="소득세 + 4대보험 등 해당 월 공제 합계"),
            "비고": st.column_config.TextColumn(),
        },
    )

    # ---- 실시간 합계 (입력값을 즉시 파싱해서 보여줌) ----
    오류 = []
    월레코드 = []
    for _, row in 편집df.iterrows():
        m = int(row["월"])
        try:
            g = S.as_number(row["월 급여(세전)"])
            b = S.as_number(row["상여금(세전)"])
            t = S.as_number(row["세금·공제"])
        except ValueError:
            오류.append(f"{m}월 금액 형식을 확인해 주세요.")
            g = b = t = 0
        if t > g + b:
            오류.append(f"{m}월: 세금·공제가 월 급여+상여금 합계보다 큽니다.")
        월레코드.append({"month": m, "gross": g, "bonus": b, "bonus_separate": True,
                      "tax": t, "note": str(row["비고"] or "").strip()})

    합세전 = sum(r["gross"] + r["bonus"] for r in 월레코드)
    합세금 = sum(r["tax"] for r in 월레코드)
    합상여 = sum(r["bonus"] for r in 월레코드)

    m1, m2, m3 = st.columns(3)
    m1.metric("월별 세전 합계", S.money(합세전))
    m2.metric("월별 세후 합계", S.money(max(0, 합세전 - 합세금)))
    m3.metric("상여금 합계", S.money(합상여))
    if 합세전:
        st.caption(f"실효 공제율 {합세금 / 합세전 * 100:.1f}%")

    for o in 오류:
        st.error(o, icon="⚠️")

    계약미리 = S.as_number(계약입력) if 계약입력.strip() else 0
    세전미리 = S.as_number(세전입력) if 세전입력.strip() else 0
    if not (계약미리 or 세전미리 or 합세전):
        st.info("계약서 연봉·실제 세전 연봉·월별 급여 중 **하나는** 넣어야 "
                "대시보드와 연도별 현황에 나타납니다. (메모만 저장해도 되지만 표에는 안 보입니다)",
                icon="💡")

    if st.button(f"💾 {연도}년 자료 저장", type="primary", width="stretch",
                 disabled=bool(오류)):
        try:
            물가텍스트 = 물가입력.strip().replace(",", ".")
            if 물가텍스트:
                float(물가텍스트)
            자료[str(연도)] = {
                "contract_annual": S.as_number(계약입력),
                "annual_gross": S.as_number(세전입력),
                "inflation": 물가텍스트,
                "note": 메모입력.strip(),
                "months": 월레코드,
            }
            성공, 메시지 = storage.저장하기("salary", 자료)
            if 성공:
                st.session_state["_연도이동"] = 연도      # 저장 후에도 같은 연도 유지
                st.success(f"{연도}년 자료를 저장했습니다. {메시지}")
                st.rerun()
            else:
                st.error(메시지)
        except ValueError:
            st.error("계약서 연봉·실제 세전 연봉의 금액 형식 또는 물가상승률(숫자)을 확인해 주세요.")

    if str(연도) in 자료:
        with st.expander("이 연도 자료 삭제"):
            if st.button(f"{연도}년 자료 삭제", width="stretch"):
                자료.pop(str(연도), None)
                storage.저장하기("salary", 자료)
                st.session_state["_연도이동"] = 연도
                st.rerun()
