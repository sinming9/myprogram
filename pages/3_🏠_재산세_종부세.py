import datetime
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines.property_tax import (AGE_OPTIONS, HOLD_OPTIONS, PropertyRow,  # noqa: E402
                                  add_or_update_history, calculate,
                                  estimate_next_year, won)

require_login(page_title="재산세·종부세 계산기", page_icon="🏠", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

st.title("🏠 재산세 · 종합부동산세 계산기")
st.caption("보유 부동산별 공시가격·지분을 넣으면 7월/9월 재산세와 12월 종부세를 계산합니다.")

기본_부동산 = [{"이름": "우리집", "공시가격(만원)": 50000.0, "지분(%)": 100.0,
             "실제 7월 고지액(선택)": None}]
기본_자료 = {
    "부동산": 기본_부동산,
    "is_one": True,
    "house_count": 1,
    "age_key": list(AGE_OPTIONS)[0],
    "hold_key": list(HOLD_OPTIONS)[0],
    "history": [],
}


def _자료_불러오기():
    저장 = storage.불러오기("property_tax", None) or {}
    자료 = dict(기본_자료)
    자료.update({k: v for k, v in 저장.items() if k in 기본_자료})
    if not 자료.get("부동산"):
        자료["부동산"] = [dict(r) for r in 기본_부동산]
    if 자료.get("age_key") not in AGE_OPTIONS:
        자료["age_key"] = list(AGE_OPTIONS)[0]
    if 자료.get("hold_key") not in HOLD_OPTIONS:
        자료["hold_key"] = list(HOLD_OPTIONS)[0]
    return 자료


# 두 키를 각각 초기화 (한쪽만 들어와도 KeyError 가 나지 않도록)
if "재산세_자료" not in st.session_state:
    st.session_state["재산세_자료"] = _자료_불러오기()
st.session_state.setdefault("재산세_표버전", 0)

자료 = st.session_state["재산세_자료"]

storage.임시서버_안내()
def _복원후(_데이터):
    st.session_state["재산세_자료"] = _자료_불러오기()
    st.session_state["재산세_표버전"] = st.session_state.get("재산세_표버전", 0) + 1


storage.백업_사이드바("property_tax", 자료, "재산세_백업", 복원_콜백=_복원후)
st.sidebar.page_link("pages/8_📥_자료_가져오기.py", label="예전 자료 올리기", icon="📥")

# ==========================================================================
# 입력
# ==========================================================================
st.subheader("1. 보유 부동산")

기준df = pd.DataFrame(자료["부동산"])
for 열, 기본 in (("이름", ""), ("공시가격(만원)", 0.0), ("지분(%)", 100.0),
              ("실제 7월 고지액(선택)", None)):
    if 열 not in 기준df.columns:
        기준df[열] = 기본
기준df = 기준df[["이름", "공시가격(만원)", "지분(%)", "실제 7월 고지액(선택)"]]
for 열 in ("공시가격(만원)", "지분(%)", "실제 7월 고지액(선택)"):
    기준df[열] = pd.to_numeric(기준df[열], errors="coerce")

부동산df = st.data_editor(
    기준df,
    num_rows="dynamic",
    width="stretch",
    key=f"부동산_editor_{st.session_state.get('재산세_표버전', 0)}",
    column_config={
        "이름": st.column_config.TextColumn(help="예: 우리집, 오피스텔"),
        "공시가격(만원)": st.column_config.NumberColumn(
            min_value=0.0, step=1000.0, format="%.0f",
            help="물건 '전체' 공시가격 (지분 반영 전). 5억이면 50000"),
        "지분(%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=5.0,
                                              format="%.1f"),
        "실제 7월 고지액(선택)": st.column_config.NumberColumn(
            min_value=0.0, step=10000.0, format="%.0f",
            help="고지서를 받았으면 물건별 금액을 넣으세요. 합산해서 9월분을 보정합니다."),
    },
)

st.subheader("2. 세대 · 공제 조건")
c1, c2 = st.columns(2)
is_one = c1.toggle("1세대 1주택자", value=bool(자료["is_one"]),
                   help="1세대 1주택이면 재산세 특례세율과 종부세 12억 공제, 고령·장기보유 세액공제가 적용됩니다.")
house_count = c2.number_input("종부세 기준 주택 수", min_value=1, max_value=20, step=1,
                              value=int(자료["house_count"]),
                              help="3주택 이상이면 종부세 중과세율이 적용됩니다.")

c3, c4 = st.columns(2)
age_key = c3.selectbox("고령자 세액공제", list(AGE_OPTIONS),
                       index=list(AGE_OPTIONS).index(자료["age_key"]),
                       disabled=not is_one)
hold_key = c4.selectbox("장기보유 세액공제", list(HOLD_OPTIONS),
                        index=list(HOLD_OPTIONS).index(자료["hold_key"]),
                        disabled=not is_one)
if not is_one:
    st.caption("고령자·장기보유 세액공제는 1세대 1주택자만 적용됩니다.")

# ==========================================================================
# 계산
# ==========================================================================
목록 = []
고지액합 = 0.0
for _, row in 부동산df.iterrows():
    if pd.isna(row.get("공시가격(만원)")) or float(row["공시가격(만원)"]) <= 0:
        continue
    목록.append(PropertyRow(
        name=str(row.get("이름") or "부동산"),
        gongsi_manwon=float(row["공시가격(만원)"]),
        share_pct=float(row["지분(%)"]) if not pd.isna(row.get("지분(%)")) else 100.0,
    ))
    고지 = row.get("실제 7월 고지액(선택)")
    if not pd.isna(고지):
        고지액합 += float(고지)

if not 목록:
    st.warning("공시가격이 입력된 부동산이 없습니다. 위 표에 한 줄 이상 입력해 주세요.", icon="📝")
    st.stop()

결과 = calculate(목록, is_one, int(house_count),
                AGE_OPTIONS[age_key], HOLD_OPTIONS[hold_key],
                고지액합 if 고지액합 > 0 else None)

# 현재 입력 상태를 세션에 반영 (저장 버튼을 누르면 파일로 기록)
자료.update({
    "부동산": [{"이름": str(r.get("이름") or ""),
              "공시가격(만원)": None if pd.isna(r.get("공시가격(만원)")) else float(r["공시가격(만원)"]),
              "지분(%)": None if pd.isna(r.get("지분(%)")) else float(r["지분(%)"]),
              "실제 7월 고지액(선택)": None if pd.isna(r.get("실제 7월 고지액(선택)"))
              else float(r["실제 7월 고지액(선택)"])}
             for _, r in 부동산df.iterrows()],
    "is_one": bool(is_one),
    "house_count": int(house_count),
    "age_key": age_key,
    "hold_key": hold_key,
})

st.divider()
st.subheader("연간 납부 예정액")
ui.카드_줄([
    ("7월 재산세", won(결과.july_total),
     "실제 고지액 기준" if 결과.paid_july else "계산값"),
    ("9월 재산세", won(결과.sep_total),
     "7월 고지액으로 보정됨" if 결과.paid_july else ("7월 일괄고지" if 결과.lump_july else "계산값")),
    ("12월 종부세+농특세", won(결과.j_total),
     "중과세율 적용" if (결과.heavy and 결과.j_base > 1.2e9) else "일반세율"),
    ("연간 합계", won(결과.july_total + 결과.sep_total + 결과.j_total), ""),
], 열수=2)

with st.expander("🏠 부동산별 재산세 상세 (연간, 내 지분 기준)", expanded=True):
    상세df = pd.DataFrame([{
        "이름": d.name,
        "공시가격(만원)": d.gongsi_manwon,
        "지분(%)": d.share_pct,
        "공정시장가액비율": f"{d.fmv * 100:.0f}%",
        "세율": d.rate_type,
        "본세": round(d.my_main),
        "도시지역분": round(d.my_city),
        "지방교육세": round(d.my_edu),
        "합계": round(d.my_total),
    } for d in 결과.details])
    st.dataframe(
        상세df.style.format({
            "공시가격(만원)": "{:,.0f}", "지분(%)": "{:.1f}",
            "본세": "{:,}", "도시지역분": "{:,}", "지방교육세": "{:,}", "합계": "{:,}",
        }),
        width="stretch", hide_index=True,
    )
    꼬리 = " (합산 20만원 이하 → 7월 일괄고지)" if 결과.lump_july else ""
    st.caption(f"전체 재산세 연간 합계: **{won(결과.p_total_sum)}**{꼬리}")

if 결과.paid_july:
    with st.expander("🧾 7월 고지액 보정 상세", expanded=True):
        st.markdown(
            f"- 계산된 7월분: {won(결과.july_calc)}\n"
            f"- 실제 고지액: {won(결과.paid_july)}\n"
            f"- 차이: {'+' if 결과.diff >= 0 else ''}{결과.diff:,.0f}원\n"
            f"- 보정 배율: × {결과.ratio:.3f} (9월분에 적용)"
        )
        if abs(결과.diff) > 결과.july_calc * 0.05:
            st.warning(
                "차이가 5%를 넘습니다. 시가표준액 차이, 세부담상한제, 지역자원시설세 포함 여부 "
                "중 하나가 원인일 수 있습니다.", icon="⚠️")

with st.expander("📄 종합부동산세 상세 (12월, 전체 합산)"):
    st.markdown(
        f"- 공제금액: {'12억원 (1세대1주택)' if 결과.is_one else '9억원'}\n"
        f"- 과세표준 (공정 60%): {won(결과.j_base)}\n"
        f"- 산출세액: {won(결과.j_gross)}"
        f"{'  ← 3주택 이상 중과세율' if (결과.heavy and 결과.j_base > 1.2e9) else ''}\n"
        f"- 재산세 중복분 공제: −{won(결과.p_credit)}\n"
        f"- 세액공제 (고령+장기): −{won(결과.age_hold_credit)}"
        f"{f'  ({결과.cred_rate * 100:.0f}%)' if 결과.cred_rate > 0 else ''}\n"
        f"- 종부세 결정세액: {won(결과.j_net)}\n"
        f"- 농어촌특별세 (20%): {won(결과.j_rural)}\n"
        f"- **12월 납부 합계: {won(결과.j_total)}**"
    )

# ==========================================================================
# 연도별 기록
# ==========================================================================
st.divider()
st.subheader("연도별 기록")

올해 = datetime.date.today().year
b1, b2 = st.columns([1, 1])
기록연도 = b1.number_input("기록할 연도", min_value=2000, max_value=2100, value=올해, step=1)
if b2.button("📅 이 결과를 연도별 기록에 저장", type="primary", width="stretch"):
    자료["history"] = add_or_update_history(
        자료.get("history", []), int(기록연도), 결과, datetime.date.today().isoformat())
    성공, 메시지 = storage.저장하기("property_tax", 자료)
    (st.success if 성공 else st.error)(메시지)

if st.button("💾 입력값만 저장 (기록 없이)", width="stretch"):
    성공, 메시지 = storage.저장하기("property_tax", 자료)
    (st.success if 성공 else st.error)(메시지)

기록 = 자료.get("history", [])
if 기록:
    기록df = pd.DataFrame(기록)
    표시 = 기록df.rename(columns={"year": "연도", "july": "7월", "sep": "9월",
                               "jongbuse": "12월 종부세", "total": "합계",
                               "saved_at": "저장일"})
    st.dataframe(
        표시.style.format({"7월": "{:,.0f}", "9월": "{:,.0f}",
                          "12월 종부세": "{:,.0f}", "합계": "{:,.0f}"}),
        width="stretch", hide_index=True,
    )

    fig = go.Figure()
    for 열, 이름, 색 in (("july", "7월 재산세", "#3457d5"),
                     ("sep", "9월 재산세", "#6C63B5"),
                     ("jongbuse", "12월 종부세", "#C0392B")):
        fig.add_trace(go.Bar(x=기록df["year"].astype(str), y=기록df[열], name=이름,
                             marker_color=색))
    fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="원", legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")

    예상 = estimate_next_year(기록)
    if 예상:
        st.info(
            f"**{예상['year']}년 예상** — 7월 {won(예상['july'])} · 9월 {won(예상['sep'])} · "
            f"12월 {won(예상['jongbuse'])} → 합계 **{won(예상['total'])}** "
            f"(연평균 증가율 {예상['avg_growth'] * 100:+.1f}% 기준)", icon="📈")
    else:
        st.caption("연도별 기록이 2개 이상 쌓이면 내년 예상 세금을 계산해 드립니다.")

    with st.expander("기록 지우기"):
        지울연도 = st.selectbox("삭제할 연도", [h["year"] for h in 기록])
        if st.button("이 연도 기록 삭제", width="stretch"):
            자료["history"] = [h for h in 기록 if h["year"] != 지울연도]
            storage.저장하기("property_tax", 자료)
            st.rerun()
else:
    st.caption("아직 기록이 없습니다. 위에서 연도를 골라 저장해 보세요.")

st.divider()
st.caption(
    "※ 간이 계산기입니다. 세부담상한제·지역자원시설세·감면 특례 및 지분 소액특례는 반영되어 있지 않습니다. "
    "정확한 세액은 홈택스 모의계산으로 확인하세요."
)
