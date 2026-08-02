"""
==========================================================================
환율 조회 / 평균 계산 엔진  (v3 - 조회 실패·이상값 대응)
==========================================================================
[v3에서 고친 것]

야후 파이낸스에는 원화 직접 교차 티커(CNYKRW=X 등)가 통화에 따라
없거나 값이 비어 있는 경우가 있습니다. 그래서 조회 경로를 늘렸습니다.

  1) 직접 티커      : CNYKRW=X  (있으면 가장 정확)
  2) 달러 경유 합성  : (USD/KRW) ÷ (USD/CNY)   ← 새로 추가
  3) stooq 직접
  4) stooq 합성

USD/KRW(KRW=X) 와 USD/외화(CNY=X 등)는 거래량이 많아 거의 항상 있습니다.
그래서 직접 티커가 없어도 2번으로 정확한 값을 만들 수 있습니다.

또 통화마다 '있을 법한 값의 범위'를 정해두고, 받아온 값이 그 범위를
벗어나면 잘못된 데이터로 보고 다음 경로로 넘어갑니다.
(예: 위안화가 1400원으로 나오면 달러 값을 잘못 받은 것)
==========================================================================
"""

from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

모듈버전 = "2026-08-02i"

AVG_COLORS = {
    "3년 평균": "#9AA3AF",
    "1년 평균": "#C9A227",
    "6개월 평균": "#B5546B",
    "3개월 평균": "#6C63B5",
    "1개월 평균": "#3B7EA1",
}
MAIN_COLOR = "#1F6F5C"

# ---------------------------------------------------------------------------
# 통화 정의
#   direct : 원화 직접 교차 티커 (야후)
#   cross  : 달러 경유 합성 방법
#            ("나누기", "KRW=X", "CNY=X")  → (USD/KRW) ÷ (USD/CNY) = 위안당 원화
#            ("곱하기", "KRW=X", "EURUSD=X") → (USD/KRW) × (EUR/USD) = 유로당 원화
#   scale  : 표시 단위 배수 (엔화는 100엔 기준이라 100)
#   범위    : scale 적용 후 상식적인 값의 범위. 벗어나면 잘못된 데이터로 판단
# ---------------------------------------------------------------------------
CURRENCIES = {
    "미국 달러 (USD)": {
        "direct": "KRW=X", "stooq": "usdkrw", "cross": None,
        "quote": "1달러", "unit": "원", "chart_label": "원 / 달러",
        "scale": 1, "범위": (500, 3000),
    },
    "일본 엔 (JPY)": {
        "direct": "JPYKRW=X", "stooq": "jpykrw",
        "cross": ("나누기", "KRW=X", "JPY=X"),
        "quote": "100엔", "unit": "원", "chart_label": "원 / 100엔",
        "scale": 100, "범위": (400, 2500),
    },
    "유로 (EUR)": {
        "direct": "EURKRW=X", "stooq": "eurkrw",
        "cross": ("곱하기", "KRW=X", "EURUSD=X"),
        "quote": "1유로", "unit": "원", "chart_label": "원 / 유로",
        "scale": 1, "범위": (700, 3500),
    },
    "중국 위안 (CNY)": {
        "direct": "CNYKRW=X", "stooq": "cnykrw",
        "cross": ("나누기", "KRW=X", "CNY=X"),
        "quote": "1위안", "unit": "원", "chart_label": "원 / 위안",
        "scale": 1, "범위": (80, 400),
    },
    "싱가포르 달러 (SGD)": {
        "direct": "SGDKRW=X", "stooq": "sgdkrw",
        "cross": ("나누기", "KRW=X", "SGD=X"),
        "quote": "1싱가포르 달러", "unit": "원", "chart_label": "원 / 싱가포르 달러",
        "scale": 1, "범위": (400, 2000),
    },
}

기간_정의 = {
    "3년 평균": ("years", 3),
    "1년 평균": ("years", 1),
    "6개월 평균": ("months", 6),
    "3개월 평균": ("months", 3),
    "1개월 평균": ("months", 1),
}


# ---------------------------------------------------------------------------
# 개별 시계열 조회
# ---------------------------------------------------------------------------
def _fdr_시리즈(symbol, start, end) -> pd.Series:
    import FinanceDataReader as fdr
    data = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if data is None or data.empty or "Close" not in data:
        raise ValueError(f"{symbol}: 응답이 비어 있습니다")
    s = pd.to_numeric(data["Close"], errors="coerce").dropna()
    if s.empty:
        raise ValueError(f"{symbol}: 유효한 종가가 없습니다")
    return s.sort_index()


def _stooq_시리즈(code, start, end) -> pd.Series:
    import urllib.request
    url = (f"https://stooq.com/q/d/l/?s={code}"
           f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d")
    with urllib.request.urlopen(url, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if not text.startswith("Date"):
        raise ValueError(f"{code}: stooq 응답 형식이 예상과 다릅니다")
    data = pd.read_csv(StringIO(text), parse_dates=["Date"]).set_index("Date")
    if data.empty or "Close" not in data:
        raise ValueError(f"{code}: stooq 응답이 비어 있습니다")
    s = pd.to_numeric(data["Close"], errors="coerce").dropna()
    if s.empty:
        raise ValueError(f"{code}: 유효한 종가가 없습니다")
    return s.sort_index()


def _합성(방법, 시리즈A, 시리즈B) -> pd.Series:
    """두 시계열을 날짜 기준으로 맞춰서 나누거나 곱합니다."""
    묶음 = pd.concat([시리즈A.rename("a"), 시리즈B.rename("b")], axis=1)
    묶음 = 묶음.ffill().dropna()
    if 묶음.empty:
        raise ValueError("합성할 두 시계열에 겹치는 날짜가 없습니다")
    결과 = 묶음["a"] / 묶음["b"] if 방법 == "나누기" else 묶음["a"] * 묶음["b"]
    return 결과.dropna()


def _범위확인(시리즈, currency):
    """가장 최근 값이 상식적인 범위 안인지. 벗어나면 예외."""
    최소, 최대 = currency.get("범위", (0, float("inf")))
    최근 = float(시리즈.iloc[-1])
    if not (최소 <= 최근 <= 최대):
        raise ValueError(f"값이 이상합니다 ({최근:,.2f} — 예상 범위 {최소:,}~{최대:,})")
    return 시리즈


def _자료충분한가(시리즈, years: int):
    """기간별 평균을 낼 만큼 이력이 있는지 확인. (충분여부, 설명) 반환.

    ※ 이 검사가 없으면, 티커는 존재하지만 이력이 며칠치뿐인 경우
      3년·1년·6개월 평균이 전부 같은 값으로 나옵니다.
      (자료가 한 점이면 어느 기간을 잘라도 그 한 점이라서)
    """
    개수 = len(시리즈)
    if 개수 < 2:
        return False, f"자료가 {개수}개뿐"
    기간일수 = (시리즈.index.max() - 시리즈.index.min()).days
    if 개수 < 60:
        return False, f"자료가 {개수}개뿐 (기간 {기간일수}일)"
    if 기간일수 < 330:
        return False, f"기간이 {기간일수}일뿐 (1년 평균도 낼 수 없음)"
    if float(시리즈.std()) == 0:
        return False, "값이 전혀 변하지 않음"
    if 기간일수 < 365 * years * 0.8:
        return False, f"기간이 {기간일수}일 ({years}년치가 안 됨)"
    return True, f"자료 {개수}개 / {기간일수}일"


# ---------------------------------------------------------------------------
# 조회 (여러 경로를 차례로 시도)
# ---------------------------------------------------------------------------
def 환율_가져오기(currency: dict, years: int = 3) -> tuple:
    """(DataFrame, 사용한_출처이름, 시도기록) 반환.

    DataFrame 의 Close 열은 표시 단위(scale 적용)로 환산된 값입니다.
    """
    end = datetime.today()
    start = end - timedelta(days=365 * years + 21)
    배수 = currency["scale"]
    cross = currency.get("cross")

    def 직접_fdr():
        return _fdr_시리즈(currency["direct"], start, end)

    def 합성_fdr():
        방법, 위, 아래 = cross
        return _합성(방법, _fdr_시리즈(위, start, end), _fdr_시리즈(아래, start, end))

    def 직접_stooq():
        return _stooq_시리즈(currency["stooq"], start, end)

    def 합성_stooq():
        방법, 위, 아래 = cross
        코드 = {"KRW=X": "usdkrw", "JPY=X": "usdjpy", "CNY=X": "usdcny",
              "SGD=X": "usdsgd", "EURUSD=X": "eurusd"}
        return _합성(방법, _stooq_시리즈(코드[위], start, end),
                   _stooq_시리즈(코드[아래], start, end))

    경로 = [("직접 조회", 직접_fdr)]
    if cross:
        방법, 위, 아래 = cross
        경로.append((f"달러 경유 합성 ({위} {'÷' if 방법 == '나누기' else '×'} {아래})", 합성_fdr))
    경로.append(("stooq 직접", 직접_stooq))
    if cross:
        경로.append(("stooq 합성", 합성_stooq))

    def _표(시리즈):
        df = pd.DataFrame({"Close": 시리즈})
        df.index.name = "Date"
        return df

    기록 = []
    아쉬운후보 = []          # 값은 정상인데 이력이 짧은 것들
    for 이름, 함수 in 경로:
        try:
            시리즈 = 함수() * 배수
            _범위확인(시리즈, currency)
            충분, 설명 = _자료충분한가(시리즈, years)
            if 충분:
                기록.append(f"{이름}: 성공 ({설명})")
                return _표(시리즈), 이름, 기록
            기록.append(f"{이름}: 자료 부족 — {설명}")
            아쉬운후보.append((시리즈, 이름, 설명))
        except Exception as e:  # noqa: BLE001
            기록.append(f"{이름}: {e}")

    if 아쉬운후보:
        # 완전한 곳이 없으면 그중 가장 이력이 긴 것을 씁니다 (경고와 함께)
        시리즈, 이름, 설명 = max(아쉬운후보, key=lambda x: len(x[0]))
        기록.append(f"→ {이름} 사용 (자료가 부족하니 긴 기간 평균은 참고만 하세요)")
        return _표(시리즈), f"{이름} · 자료 부족({설명})", 기록

    raise RuntimeError("환율 데이터를 가져오지 못했습니다.\n" + "\n".join(기록))


# ---------------------------------------------------------------------------
# 계산
# ---------------------------------------------------------------------------
def 평균_계산(data: pd.DataFrame):
    """(평균dict, 신뢰가능dict) 반환.

    자료가 그 기간을 제대로 덮지 못하면 신뢰가능=False 로 표시합니다.
    이걸 구분하지 않으면 이력이 짧을 때 3년·1년 평균이 전부 같은 값으로
    나오면서 마치 정상인 것처럼 보입니다.
    """
    latest = data.index.max()
    earliest = data.index.min()
    평균, 신뢰 = {}, {}
    for 라벨, (단위, 값) in 기간_정의.items():
        시작 = latest - (pd.DateOffset(years=값) if 단위 == "years"
                       else pd.DateOffset(months=값))
        구간 = data.loc[data.index >= 시작, "Close"]
        평균[라벨] = float(구간.mean()) if len(구간) else float("nan")

        요청일수 = max((latest - 시작).days, 1)
        실제일수 = (latest - max(시작, earliest)).days
        신뢰[라벨] = (실제일수 >= 요청일수 * 0.8) and len(구간) >= 15
    return 평균, 신뢰


def 금액표시(값, 단위="원") -> str:
    """통화 단위에 맞춰 소수 자릿수를 자동으로 정합니다.

    ※ 예전에는 무조건 정수로 반올림했습니다. 달러(~1,390원)는 괜찮지만
      위안화(~195원)는 1원이 0.5%나 되어서, 기간별 평균이 조금씩 달라도
      화면에는 전부 같은 숫자로 보였습니다.
    """
    try:
        v = float(값)
    except (TypeError, ValueError):
        return "-"
    if v != v:                       # NaN
        return "-"
    자릿수 = 0 if abs(v) >= 500 else (2 if abs(v) >= 50 else 4)
    return f"{v:,.{자릿수}f}{단위}"


def 타이밍_메시지(저렴한_구간수: int) -> tuple:
    if 저렴한_구간수 >= 4:
        return "success", "과거 평균 대비 낮은 편이에요. 환전하기 나쁘지 않은 시점일 수 있어요."
    if 저렴한_구간수 <= 1:
        return "warning", "과거 평균 대비 높은 편이에요. 나눠서 환전하거나 조금 더 지켜보는 방법도 있어요."
    return "info", "과거 평균과 비슷한 수준이에요. 필요한 금액과 시점을 함께 고려해 보세요."
