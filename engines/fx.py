"""
==========================================================================
환율 조회 / 평균 계산 엔진
==========================================================================
exchange_rate_dashboard.py 의 데이터 처리 부분을 분리한 것입니다.

데이터 출처를 2단계로 두었습니다.
 1) FinanceDataReader (설치되어 있으면 우선 사용)
 2) stooq CSV 직접 조회 (FinanceDataReader 설치/설정 문제 시 대체)
둘 다 실패하면 예외를 던지고, 화면에서 안내 메시지를 보여줍니다.
==========================================================================
"""

from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

AVG_COLORS = {
    "3년 평균": "#9AA3AF",
    "1년 평균": "#C9A227",
    "6개월 평균": "#B5546B",
    "3개월 평균": "#6C63B5",
    "1개월 평균": "#3B7EA1",
}
MAIN_COLOR = "#1F6F5C"

# 엔화는 한국에서 익숙한 '100엔당 원화' 기준으로 보여줍니다.
CURRENCIES = {
    "미국 달러 (USD)": {
        "symbol": "KRW=X", "stooq": "usdkrw",
        "quote": "1달러", "unit": "원", "chart_label": "원 / 달러", "scale": 1,
    },
    "일본 엔 (JPY)": {
        "symbol": "JPYKRW=X", "stooq": "jpykrw",
        "quote": "100엔", "unit": "원", "chart_label": "원 / 100엔", "scale": 100,
    },
    "유로 (EUR)": {
        "symbol": "EURKRW=X", "stooq": "eurkrw",
        "quote": "1유로", "unit": "원", "chart_label": "원 / 유로", "scale": 1,
    },
    "중국 위안 (CNY)": {
        "symbol": "CNYKRW=X", "stooq": "cnykrw",
        "quote": "1위안", "unit": "원", "chart_label": "원 / 위안", "scale": 1,
    },
    "싱가포르 달러 (SGD)": {
        "symbol": "SGDKRW=X", "stooq": "sgdkrw",
        "quote": "1싱가포르 달러", "unit": "원", "chart_label": "원 / 싱가포르 달러", "scale": 1,
    },
}

기간_정의 = {
    "3년 평균": ("years", 3),
    "1년 평균": ("years", 1),
    "6개월 평균": ("months", 6),
    "3개월 평균": ("months", 3),
    "1개월 평균": ("months", 1),
}


def _fdr_조회(symbol, start, end):
    import FinanceDataReader as fdr
    data = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if data is None or data.empty or "Close" not in data:
        raise ValueError("FinanceDataReader 응답이 비어 있습니다.")
    return data[["Close"]].copy()


def _stooq_조회(code, start, end):
    import urllib.request
    url = (f"https://stooq.com/q/d/l/?s={code}"
           f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d")
    with urllib.request.urlopen(url, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if "Date" not in text.split("\n")[0]:
        raise ValueError("stooq 응답 형식이 예상과 다릅니다.")
    data = pd.read_csv(StringIO(text), parse_dates=["Date"]).set_index("Date")
    if data.empty or "Close" not in data:
        raise ValueError("stooq 응답이 비어 있습니다.")
    return data[["Close"]].copy()


def 환율_가져오기(currency: dict, years: int = 3) -> tuple:
    """(DataFrame, 사용한_출처이름) 반환. Close 열은 표시 단위로 환산된 값."""
    end = datetime.today()
    start = end - timedelta(days=365 * years + 21)

    오류 = []
    for 이름, 함수, 인자 in (
        ("FinanceDataReader", _fdr_조회, currency["symbol"]),
        ("stooq", _stooq_조회, currency["stooq"]),
    ):
        try:
            data = 함수(인자, start, end)
            data["Close"] = pd.to_numeric(data["Close"], errors="coerce") * currency["scale"]
            data = data.dropna(subset=["Close"]).sort_index()
            if data.empty:
                raise ValueError("유효한 종가가 없습니다.")
            return data, 이름
        except Exception as e:  # noqa: BLE001
            오류.append(f"{이름}: {e}")

    raise RuntimeError("환율 데이터를 가져오지 못했습니다.\n" + "\n".join(오류))


def 평균_계산(data: pd.DataFrame) -> dict:
    latest = data.index.max()
    result = {}
    for 라벨, (단위, 값) in 기간_정의.items():
        시작 = latest - (pd.DateOffset(years=값) if 단위 == "years" else pd.DateOffset(months=값))
        result[라벨] = float(data.loc[data.index >= 시작, "Close"].mean())
    return result


def 타이밍_메시지(저렴한_구간수: int) -> tuple:
    if 저렴한_구간수 >= 4:
        return "success", "과거 평균 대비 낮은 편이에요. 환전하기 나쁘지 않은 시점일 수 있어요."
    if 저렴한_구간수 <= 1:
        return "warning", "과거 평균 대비 높은 편이에요. 나눠서 환전하거나 조금 더 지켜보는 방법도 있어요."
    return "info", "과거 평균과 비슷한 수준이에요. 필요한 금액과 시점을 함께 고려해 보세요."
