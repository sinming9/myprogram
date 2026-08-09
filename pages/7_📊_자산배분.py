import os
import sys
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import 불러온것_적용, 저장_불러오기  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import portfolio as PF  # noqa: E402

require_login(page_title="자산배분 현황", page_icon="📊", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("📊 자산배분 현황")
st.caption("한국·미국 주식과 ETF 를 계좌별로 모아서 봅니다")

저장키 = "portfolio"
기본종목 = [
    {"이름": "삼성전자", "티커": "005930", "시장": "KR", "계좌": "일반",
     "자산군": "국내주식", "종류": "개별주", "수량": 100, "평균단가": 72000,
     "현재가(수동)": None, "평가액(직접입력)": None, "갱신일": None,
     "주당배당(수동)": None},
    {"이름": "비트코인", "티커": "BTC", "시장": "COIN", "계좌": "거래소·지갑",
     "자산군": "암호화폐", "종류": "기타", "수량": 0.01, "평균단가": 95_000_000,
     "현재가(수동)": None, "평가액(직접입력)": None, "갱신일": None,
     "주당배당(수동)": None},
]

st.session_state.setdefault("자산_종목", [dict(r) for r in 기본종목])
st.session_state.setdefault("자산_목표", {})
st.session_state.setdefault("자산_ISA", {})
st.session_state.setdefault("자산_표버전", 0)

if not st.session_state.get("_자산_자동로드"):
    st.session_state["_자산_자동로드"] = True
    저장된 = storage.불러오기(저장키, None)
    if 저장된 and isinstance(저장된, dict) and 저장된.get("종목"):
        st.session_state["자산_종목"] = 저장된["종목"]
        st.session_state["자산_목표"] = 저장된.get("목표") or {}
        st.session_state["자산_ISA"] = 저장된.get("ISA") or {}


def _설정_적용(데이터):
    if isinstance(데이터, dict) and 데이터.get("종목") is not None:
        st.session_state["자산_종목"] = 데이터["종목"]
        st.session_state["자산_목표"] = 데이터.get("목표") or {}
        st.session_state["자산_ISA"] = 데이터.get("ISA") or {}
        st.session_state["자산_표버전"] += 1


불러온것_적용("_자산_적용대기", _설정_적용)
storage.임시서버_안내()

# ==========================================================================
# 입력
# ==========================================================================
st.subheader("보유 종목")
st.caption("**자산군**은 직접 골라주세요. 예를 들어 국내 상장 미국 ETF 는 "
           "시장은 KR 이지만 자산군은 해외주식입니다. 이걸 구분해야 실제 "
           "자산배분이 보입니다.")
st.caption("**비트코인 등 암호화폐**는 시장을 `COIN`, 티커에 심볼(`BTC`, `ETH`)만 "
           "넣으세요. 업비트 원화 시세를 먼저 보고, 없으면 야후의 달러 시세를 "
           "환율로 환산합니다. **평균단가는 원화로** 넣으세요.")
st.caption("**퇴직연금(DC)·IRP 의 TDF·펀드·정기예금**은 티커가 없어 시세 조회가 "
           "안 됩니다. 종류를 `펀드/TDF` 나 `원리금보장` 으로 고르고, "
           "**평가액(직접입력)** 에 현재 평가금액을 넣으세요. "
           "수량 1 · 평균단가에 투자원금을 넣으면 손익까지 나옵니다.")

열 = ["이름", "티커", "시장", "계좌", "자산군", "종류", "수량", "평균단가",
     "현재가(수동)", "평가액(직접입력)", "갱신일", "주당배당(수동)"]
기준df = pd.DataFrame(st.session_state["자산_종목"], columns=열)
for 숫자열 in ("수량", "평균단가", "현재가(수동)", "평가액(직접입력)",
            "주당배당(수동)"):
    기준df[숫자열] = pd.to_numeric(기준df[숫자열], errors="coerce")
# 날짜 열은 object dtype 으로 (datetime64 면 pandas 3.x 에서 편집이 안 됩니다)
기준df["갱신일"] = pd.Series(
    [None if pd.isna(v) else (v if isinstance(v, date)
                              else pd.to_datetime(v, errors="coerce").date()
                              if pd.notna(pd.to_datetime(v, errors="coerce")) else None)
     for v in 기준df["갱신일"]], dtype="object")

종목df = st.data_editor(
    기준df, num_rows="dynamic", width="stretch",
    key=f"자산_editor_{st.session_state.get('자산_표버전', 0)}",
    column_config={
        "이름": st.column_config.TextColumn(width="medium"),
        "티커": st.column_config.TextColumn(
            help="한국 6자리 숫자(005930) · 미국 심볼(AAPL) · 코인 심볼(BTC, ETH)"),
        "시장": st.column_config.SelectboxColumn(options=PF.시장목록),
        "계좌": st.column_config.SelectboxColumn(options=PF.계좌목록),
        "자산군": st.column_config.SelectboxColumn(options=PF.자산군목록),
        "종류": st.column_config.SelectboxColumn(options=PF.종류목록),
        "수량": st.column_config.NumberColumn(
            min_value=0.0, step=0.00000001, format="%.8f",
            help="소수점 8자리까지 넣을 수 있습니다. "
                 "해외주식 소수점 매수, 펀드 좌수, 비트코인(사토시 8자리) 등에 쓰세요. "
                 "펀드·예금처럼 수량 개념이 없으면 1 을 넣으세요."),
        "평균단가": st.column_config.NumberColumn(
            min_value=0.0, step=100.0, format="%.4f",
            help="원래 통화로 넣으세요 — 해외주식은 달러($180), "
                 "국내주식·코인은 원화(72000)"),
        "현재가(수동)": st.column_config.NumberColumn(
            min_value=0.0, format="%.4f",
            help="자동 조회가 안 되는 종목만. 평균단가와 같은 통화로 넣으세요"),
        "평가액(직접입력)": st.column_config.NumberColumn(
            min_value=0.0, format="%d",
            help="퇴직연금 TDF·펀드·정기예금처럼 티커가 없는 상품용. "
                 "여기 넣으면 시세 조회를 건너뛰고 이 금액을 그대로 씁니다. "
                 "수량 1, 평균단가에 투자원금을 넣으면 손익도 나옵니다."),
        "갱신일": st.column_config.DateColumn(
            format="YYYY-MM-DD",
            help="평가액을 직접 넣은 날. 30일이 지나면 알려드립니다."),
        "주당배당(수동)": st.column_config.NumberColumn(
            min_value=0.0, help="비워두면 최근 1년 실제 배당을 씁니다"),
    })

읽은목록 = []
문제 = []
for 순번, (_, row) in enumerate(종목df.iterrows(), start=1):
    이름 = str(row.get("이름") or "").strip()
    티커 = str(row.get("티커") or "").strip()
    수량 = row.get("수량")
    if not 이름 and not 티커:
        continue
    if pd.isna(수량) or float(수량) <= 0:
        문제.append(f"{순번}번째 줄({이름 or 티커}): 수량이 비어 있습니다. "
                  "펀드·예금처럼 수량 개념이 없으면 1 을 넣으세요.")
        continue
    읽은목록.append({
        "이름": 이름 or 티커, "티커": 티커,
        "시장": row.get("시장") or "KR", "계좌": row.get("계좌") or "일반",
        "자산군": row.get("자산군") or "기타", "종류": row.get("종류") or "개별주",
        "수량": float(수량),
        "평균단가": 0.0 if pd.isna(row.get("평균단가")) else float(row["평균단가"]),
        "현재가(수동)": None if pd.isna(row.get("현재가(수동)")) else float(row["현재가(수동)"]),
        "평가액(직접입력)": (None if pd.isna(row.get("평가액(직접입력)"))
                       else float(row["평가액(직접입력)"])),
        "갱신일": (None if not row.get("갱신일") or pd.isna(row.get("갱신일"))
                else (row["갱신일"].isoformat() if isinstance(row["갱신일"], date)
                      else str(row["갱신일"])[:10])),
        "주당배당(수동)": None if pd.isna(row.get("주당배당(수동)")) else float(row["주당배당(수동)"]),
    })

for m in 문제:
    st.warning(m, icon="⚠️")

if not 읽은목록:
    st.info("보유 종목을 한 줄 이상 입력해 주세요.", icon="📝")
    저장_불러오기(저장키, {"종목": 읽은목록,
                      "목표": st.session_state.get("자산_목표", {}),
                      "ISA": st.session_state.get("자산_ISA", {})},
              "자산배분", "_자산_적용대기")
    st.stop()

# ==========================================================================
# 시세 조회
# ==========================================================================
c1, c2 = st.columns([3, 1])
_조회대상 = sum(1 for s in 읽은목록 if PF.조회가_필요한가(s))
c1.caption(f"종목 {len(읽은목록)}개 (시세 조회 {_조회대상}개) · 30분간 기억합니다")
if c2.button("🔄 시세 새로고침", width="stretch"):
    st.cache_data.clear()
    st.rerun()


@st.cache_data(ttl=1800, show_spinner=False)
def 시세_모으기(키목록):
    결과, 실패 = {}, []
    for 이름, 티커, 시장 in 키목록:
        try:
            결과[이름] = PF.시세_조회(티커, 시장)
        except Exception as e:  # noqa: BLE001
            실패.append(f"{이름}({티커}): {e}")
    return 결과, 실패


@st.cache_data(ttl=1800, show_spinner=False)
def 환율_가져오기():
    try:
        return PF.환율_조회(), None
    except Exception as e:  # noqa: BLE001
        return 1390.0, str(e)


with st.spinner("시세를 불러오는 중이에요..."):
    # 티커가 없거나 평가액을 직접 넣은 줄은 조회하지 않습니다 (호출 절약)
    키목록 = tuple((s["이름"], s["티커"], s["시장"]) for s in 읽은목록
                if PF.조회가_필요한가(s))
    시세들, 실패목록 = 시세_모으기(키목록)
    환율, 환율오류 = 환율_가져오기()

if 환율오류:
    st.warning(f"환율을 받지 못해 {환율:,.0f}원으로 계산합니다. ({환율오류})", icon="⚠️")

종목들 = [PF.종목_계산(s, 시세들.get(s["이름"]), 환율) for s in 읽은목록]
합계 = PF.요약(종목들)

제약문제 = PF.계좌_제약_점검(
    [PF.종목_계산(x, None, 1.0) for x in 읽은목록])
for m in 제약문제:
    st.warning(m, icon="🚫")

오래된 = []
for s_ in 읽은목록:
    오래, 경과 = PF.갱신_필요한가(s_)
    if 오래:
        오래된.append((s_["이름"], 경과))
if 오래된:
    줄 = ", ".join(f"{이름}" + (f"({경과}일 전)" if 경과 is not None else "(날짜 없음)")
                 for 이름, 경과 in 오래된)
    st.warning(f"직접 넣은 평가액이 오래됐거나 갱신일이 비어 있습니다 — {줄}. "
               "퇴직연금 앱에서 현재 평가금액을 확인해 **갱신일**과 함께 넣어주세요.",
               icon="🗓️")

if 실패목록:
    with st.expander(f"⚠️ 시세 조회 실패 {len(실패목록)}건 — 평균단가로 계산했습니다"):
        for m in 실패목록:
            st.text("  " + m)
        st.caption(
            "**신규 상장 ETF** 는 야후에 아직 안 올라온 경우가 많습니다. "
            "그럴 땐 표의 **현재가(수동)** 에 현재가를 넣으시면 그대로 계산됩니다.\n\n"
            "한국 종목코드는 6자리입니다 — 숫자만 있는 것(`005930`)도 있고 "
            "영문이 섞인 것(`0117V0`)도 있는데 둘 다 됩니다. "
            "미국은 심볼(`AAPL`), 코인은 `BTC` 처럼 넣으세요.")

# ==========================================================================
# 요약
# ==========================================================================
st.divider()
ui.카드_줄([
    ("총 평가액", ui.억(합계["평가액"]),
     f"원화 {합계['원화자산'] / 1e8:.2f}억 + 달러 ${합계['달러자산']:,.0f}"),
    ("평가손익", ui.억(합계["손익"]), f"{합계['수익률']:+.2f}%"),
    ("연 배당(추정)", ui.억(합계["연배당"]),
     f"수익률 {합계['배당수익률']:.2f}% · 월평균 {합계['월평균배당'] / 1e4:,.0f}만"),
    ("달러 노출", f"{합계['달러비중']:.1f}%",
     f"${합계['달러자산']:,.0f} · 환율 {환율:,.0f}원"),
], 열수=2)

# ==========================================================================
# 배분 차트
# ==========================================================================
st.divider()
st.subheader("어떻게 나뉘어 있나")

기준 = st.radio("기준", ["계좌", "자산군", "시장", "종류"], horizontal=True,
              key="자산_기준")
묶음 = PF.집계(종목들, 기준)

색 = ["#2B6ED5", "#18A57A", "#E28A2B", "#C0392B", "#8E7CC3",
     "#3B7EA1", "#9AA3AF", "#B5546B"]
도넛 = go.Figure(go.Pie(
    labels=[g["이름"] for g in 묶음], values=[g["평가액"] for g in 묶음],
    hole=0.55, marker=dict(colors=색[:len(묶음)]),
    textinfo="label+percent",
    hovertemplate="%{label}<br>%{value:,.0f}원<br>%{percent}<extra></extra>"))
도넛.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10),
                 showlegend=False)
st.plotly_chart(도넛, width="stretch")

묶음표 = pd.DataFrame([{
    기준: g["이름"], "평가액": round(g["평가액"]), "비중(%)": round(g["비중"], 1),
    "종목수": g["종목수"], "손익": round(g["손익"]), "수익률(%)": round(g["수익률"], 2),
    "연배당": round(g["연배당"]),
} for g in 묶음])
st.dataframe(묶음표.style.format({"평가액": "{:,}", "손익": "{:,}", "연배당": "{:,}"}),
             width="stretch", hide_index=True)

if 기준 == "계좌":
    st.caption("계좌별 배당 과세가 다릅니다:")
    과세표 = pd.DataFrame([{
        "계좌": g["이름"],
        "평가액": round(g["평가액"]),
        "연배당": round(g["연배당"]),
        "배당 과세": PF.계좌_과세.get(g["이름"], ("-", ""))[0],
        "설명": PF.계좌_과세.get(g["이름"], ("-", ""))[1],
    } for g in 묶음])
    st.dataframe(과세표.style.format({"평가액": "{:,}", "연배당": "{:,}"}),
                 width="stretch", hide_index=True)

# ==========================================================================
# 종목별
# ==========================================================================
st.divider()
st.subheader("종목별 현황")

집중 = PF.집중도(종목들, 상위=5)
st.caption(f"상위 5종목이 전체의 **{집중['상위비중']:.1f}%** · "
           f"가장 큰 종목은 {집중['최대종목']} **{집중['최대종목비중']:.1f}%**")
if 집중["최대종목비중"] >= 30:
    st.warning(f"{집중['최대종목']} 하나가 {집중['최대종목비중']:.1f}% 입니다. "
               "한 종목 쏠림이 큰 편인지 확인해 보세요.", icon="📌")

정렬 = sorted(종목들, key=lambda s: -s["평가액"])
막대 = go.Figure(go.Bar(
    x=[s["평가액"] / 1e4 for s in 정렬][::-1],
    y=[s["이름"] for s in 정렬][::-1],
    orientation="h", marker_color="#2B6ED5",
    hovertemplate="%{y}<br>%{x:,.0f}만원<extra></extra>"))
막대.update_layout(height=max(240, 32 * len(정렬)),
                 margin=dict(l=10, r=10, t=20, b=10),
                 xaxis_title="평가액(만원)")
st.plotly_chart(막대, width="stretch")

종목표 = pd.DataFrame([{
    "이름": s["이름"], "계좌": s["계좌"], "자산군": s["자산군"], "종류": s["종류"],
    "평균단가": PF.금액표시(s["평균단가"], s["시장"]),
    "현재가": PF.금액표시(s["현재가"], s["시장"]),
    "평가액": PF.금액표시(s["현지평가액"], s["시장"]),
    "평가액(원화)": round(s["평가액"]),
    "비중(%)": round(s["평가액"] / 합계["평가액"] * 100, 1) if 합계["평가액"] else 0,
    "수익률(%)": round(s["수익률"], 2),
    "연배당": PF.금액표시(s["현지연배당"], s["시장"]),
    "배당률(%)": round(s["배당수익률"], 2),
    "52주(%)": None if s["52주위치"] is None else round(s["52주위치"]),
    "직접": "○" if s.get("직접입력") else "",
} for s in 정렬])
st.dataframe(종목표.style.format({"평가액(원화)": "{:,}"}, na_rep="-"),
             width="stretch", hide_index=True, height=min(60 + 35 * len(종목표), 500))
st.caption("**평균단가·현재가·평가액**은 원래 통화로 표시합니다 "
           "(해외주식 달러, 국내주식·코인 원화). "
           "**평가액(원화)** 는 환율로 환산한 값이고, 비중·합계는 이걸로 계산합니다.")
st.caption("**52주 위치**는 최근 1년 최저가를 0%, 최고가를 100%로 봤을 때 지금 위치입니다. "
           "높다고 팔고 낮다고 사라는 뜻이 아니라, 현재 상태를 보는 참고값입니다.")

# ==========================================================================
# 배당 달력
# ==========================================================================
st.divider()
st.subheader("📅 배당 달력")

달력 = PF.배당_달력(종목들, 환율)
연배당합 = sum(d["금액"] for d in 달력)

달력그림 = go.Figure(go.Bar(
    x=[f"{d['월']}월" for d in 달력], y=[d["금액"] / 1e4 for d in 달력],
    marker_color="#18A57A",
    customdata=[", ".join(dict.fromkeys(d["종목들"])) or "-" for d in 달력],
    hovertemplate="%{x}<br>%{y:,.0f}만원<br>%{customdata}<extra></extra>"))
달력그림.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10),
                   yaxis_title="배당(만원)")
st.plotly_chart(달력그림, width="stretch")

최다 = max(달력, key=lambda d: d["금액"])
if 연배당합 > 0:
    st.caption(f"연 {연배당합 / 1e4:,.0f}만원 · 월평균 {연배당합 / 12 / 1e4:,.0f}만원 · "
               f"가장 많은 달은 **{최다['월']}월 {최다['금액'] / 1e4:,.0f}만원** "
               f"({최다['금액'] / 연배당합 * 100:.0f}%)")
    if 최다["금액"] / 연배당합 > 0.4:
        st.info(f"{최다['월']}월에 배당이 몰려 있습니다. 한국 주식은 대개 12월 결산 후 "
                "4월에 한 번 주고, 미국은 분기로 나눠 줍니다. 매달 현금이 필요하시면 "
                "이 분포를 참고하세요.", icon="📌")

with st.expander("월별 상세"):
    달력표 = pd.DataFrame([{
        "월": f"{d['월']}월", "배당금": round(d["금액"]),
        "비중(%)": round(d["금액"] / 연배당합 * 100, 1) if 연배당합 else 0,
        "종목": ", ".join(dict.fromkeys(d["종목들"])) or "-",
    } for d in 달력])
    st.dataframe(달력표.style.format({"배당금": "{:,}"}), width="stretch",
                 hide_index=True, height=460)
    st.caption("최근 1년에 **실제로 지급된 달**을 그대로 다음 1년에 대입한 것입니다. "
               "예측이 아니라 실적이며, 회사가 배당 시기나 금액을 바꾸면 달라집니다. "
               "'(가정)' 이 붙은 건 조회가 안 돼서 한국 4월·미국 분기로 가정한 것입니다.")

# ==========================================================================
# 목표 배분 대비
# ==========================================================================
st.divider()
st.subheader("⚖️ 목표 배분 대비")

목표기준 = st.radio("무엇을 기준으로 맞출까요", ["자산군", "계좌", "시장"],
                horizontal=True, key="자산_목표기준")
항목들 = [g["이름"] for g in PF.집계(종목들, 목표기준)]
저장목표 = st.session_state.get("자산_목표", {}) or {}

st.caption("목표 비중(%)을 넣으세요. 합계가 100%가 되도록 맞추시면 됩니다.")
목표 = {}
칸수 = min(len(항목들), 3) or 1
for i in range(0, len(항목들), 칸수):
    묶 = 항목들[i:i + 칸수]
    cols = st.columns(len(묶))
    for col, 이름 in zip(cols, 묶):
        목표[이름] = col.number_input(
            이름, min_value=0.0, max_value=100.0, step=5.0,
            value=float(저장목표.get(이름, 0)), key=f"목표_{목표기준}_{이름}")

합계목표 = PF.목표_합계(목표)
if 합계목표 == 0:
    st.info("목표 비중을 넣으면 지금과 얼마나 벌어졌는지, 얼마를 조정해야 하는지 "
            "계산해 드립니다.", icon="📝")
else:
    if abs(합계목표 - 100) > 0.5:
        st.warning(f"목표 합계가 {합계목표:.0f}% 입니다. 100%로 맞춰주세요.", icon="⚠️")
    st.session_state["자산_목표"] = {k: v for k, v in 목표.items() if v}

    조정 = PF.리밸런싱(종목들, 목표, 목표기준)
    괴리그림 = go.Figure(go.Bar(
        x=[r["괴리"] for r in 조정][::-1], y=[r["이름"] for r in 조정][::-1],
        orientation="h",
        marker_color=["#C0392B" if r["괴리"] > 0 else "#2B6ED5"
                      for r in 조정][::-1],
        hovertemplate="%{y}<br>괴리 %{x:+.1f}%p<extra></extra>"))
    괴리그림.add_vline(x=0, line_color="rgba(140,140,140,.8)")
    괴리그림.update_layout(height=max(220, 42 * len(조정)),
                       margin=dict(l=10, r=10, t=20, b=10),
                       xaxis_title="목표 대비 괴리(%p) — 빨강 많음 / 파랑 적음")
    st.plotly_chart(괴리그림, width="stretch")

    조정표 = pd.DataFrame([{
        목표기준: r["이름"],
        "현재(%)": round(r["현재비중"], 1), "목표(%)": round(r["목표비중"], 1),
        "괴리(%p)": round(r["괴리"], 1),
        "현재금액": round(r["현재금액"]), "목표금액": round(r["목표금액"]),
        "조정": ("＋" if r["조정금액"] > 0 else "－") + f"{abs(r['조정금액']):,.0f}",
    } for r in 조정])
    st.dataframe(조정표.style.format({"현재금액": "{:,}", "목표금액": "{:,}"}),
                 width="stretch", hide_index=True)
    st.caption("**＋는 더 사야 할 금액, －는 덜어내야 할 금액**입니다. "
               "한 번에 맞추기보다 새로 넣는 돈으로 부족한 쪽을 채우면 "
               "매도 세금과 수수료를 아낄 수 있습니다.")

# ==========================================================================
# ISA 관리
# ==========================================================================
st.divider()
st.subheader("🏦 ISA 관리")

ISA저장 = st.session_state.get("자산_ISA", {}) or {}
ISA평가액 = sum(s["평가액"] for s in 종목들 if s.get("계좌") == "ISA")
ISA원금 = sum(s["원금"] for s in 종목들 if s.get("계좌") == "ISA")

with st.expander("ISA 정보 입력", expanded=not ISA저장):
    i1, i2 = st.columns(2)
    ISA가입일 = i1.date_input(
        "가입일", value=date.fromisoformat(ISA저장.get("가입일", "2024-01-02")),
        min_value=date(2016, 1, 1), max_value=date(2100, 12, 31), key="ISA_가입일")
    ISA유형 = i2.selectbox("유형", ["일반형", "서민형/농어민형"],
                        index=["일반형", "서민형/농어민형"].index(
                            ISA저장.get("유형", "일반형"))
                        if ISA저장.get("유형") in ("일반형", "서민형/농어민형") else 0,
                        key="ISA_유형",
                        help="총급여 5,000만원 이하 또는 종합소득 3,800만원 이하면 서민형")

    i3, i4 = st.columns(2)
    ISA총납입 = i3.number_input("지금까지 총 납입액(원)", min_value=0, step=1_000_000,
                           value=int(ISA저장.get("총납입액", 0)), key="ISA_총납입")
    ISA올해납입 = i4.number_input("올해 납입액(원)", min_value=0, step=1_000_000,
                            value=int(ISA저장.get("올해납입액", 0)), key="ISA_올해납입")

    ISA제도 = st.radio("적용 제도", list(PF.ISA_제도), horizontal=True,
                    index=list(PF.ISA_제도).index(ISA저장.get("제도", "현행"))
                    if ISA저장.get("제도") in PF.ISA_제도 else 0,
                    format_func=lambda k: PF.ISA_제도[k]["이름"], key="ISA_제도")
    if ISA제도 == "개편안":
        st.caption("정부가 「2026년 경제성장전략」에서 발표한 확대안입니다. "
                   "**국회 입법이 남아 있어 확정된 것이 아닙니다.**")
    else:
        st.caption("현행 기준입니다 — 연 2,000만/총 1억, 비과세 일반 200만·서민 400만")

    순이익입력 = st.number_input(
        "ISA 계좌 순이익(원)", min_value=0, step=100_000,
        value=int(ISA저장.get("순이익") or max(ISA평가액 - ISA원금, 0)),
        key="ISA_순이익",
        help="ISA 는 계좌 안의 손익을 통산한 뒤 과세합니다. "
             "이자·배당까지 포함한 순이익을 넣으세요.")

st.session_state["자산_ISA"] = {
    "가입일": ISA가입일.isoformat(), "유형": ISA유형,
    "총납입액": int(ISA총납입), "올해납입액": int(ISA올해납입),
    "제도": ISA제도, "순이익": int(순이익입력),
}

ISA = PF.ISA_현황(ISA가입일, ISA총납입, ISA올해납입, 순이익입력,
                ISA유형, ISA제도)

ui.카드_줄([
    ("의무기간", "충족 ✓" if ISA["의무기간_충족"] else f"D-{ISA['남은일']}",
     f"만기 {ISA['만기일']}"),
    ("비과세 잔여", ui.원(ISA["비과세잔여"]),
     f"한도 {ISA['비과세한도'] / 1e4:,.0f}만 중 {ISA['비과세소진률']:.0f}% 사용"),
    ("ISA 절세액", ui.원(ISA["절세액"]),
     f"일반계좌면 {ISA['일반계좌세금'] / 1e4:,.0f}만 → ISA {ISA['ISA세금'] / 1e4:,.0f}만"),
    ("올해 납입 여력", ui.원(ISA["연납입잔여"]),
     f"총 여력 {ISA['총납입잔여'] / 1e8:.2f}억"),
], 열수=2)

st.progress(min(ISA["진행률"] / 100, 1.0),
            text=f"의무기간 {ISA['진행률']:.0f}% 경과")
st.progress(min(ISA["비과세소진률"] / 100, 1.0),
            text=f"비과세 한도 {ISA['비과세소진률']:.0f}% 소진")

if not ISA["의무기간_충족"]:
    st.warning(f"의무 가입기간 3년이 아직 안 됐습니다 (만기 {ISA['만기일']}, "
               f"{ISA['남은일']}일 남음). 그 전에 해지하면 받은 세제 혜택을 "
               "반환하고 15.4% 과세됩니다.", icon="⏳")
elif ISA["비과세잔여"] <= 0:
    st.info("비과세 한도를 다 썼습니다. 만기 후 재가입하면 한도가 새로 생깁니다. "
            "초과 수익은 9.9% 분리과세라 일반계좌(15.4%)보다는 여전히 유리합니다.",
            icon="💡")
else:
    st.success(f"의무기간을 채웠고 비과세 한도가 {ISA['비과세잔여'] / 1e4:,.0f}만원 "
               "남아 있습니다.", icon="✓")

st.caption("※ 중도 인출은 가능하지만 인출한 만큼 납입 한도가 복구되지 않습니다. "
           "ISA 안에서는 해외 주식을 직접 살 수 없고, 국내 상장 해외 ETF 는 됩니다.")

st.divider()
st.info(
    "**주가 예측은 넣지 않았습니다.** 과거 데이터로 추세선을 긋고 '내년엔 여기쯤' 이라고 "
    "표시하는 건 기술적으로 쉽지만, 맞을 근거가 없는 숫자를 화면에 띄우면 믿게 됩니다. "
    "그래서 현황(비중·손익·52주 위치)만 보여줍니다.\n\n"
    "**암호화폐**는 원화 거래소(업비트)와 해외 시세에 차이가 납니다(김치 프리미엄). "
    "어디에 보유 중인지에 따라 실제 가치가 달라지니, 조회 출처를 확인하세요.\n\n"
    "배당은 **최근 1년 실제 지급액** 기준입니다. 앞으로도 같다는 보장은 없습니다. "
    "배당이 바뀌었으면 표의 **주당배당(수동)** 에 직접 넣으세요.", icon="ℹ️")

저장_불러오기(저장키,
          {"종목": 읽은목록,
           "목표": st.session_state.get("자산_목표", {}),
           "ISA": st.session_state.get("자산_ISA", {})},
          "자산배분", "_자산_적용대기",
          도움말="종목·목표배분·ISA 정보가 함께 저장됩니다.")
