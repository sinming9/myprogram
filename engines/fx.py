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

import re
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

모듈버전 = "2026-09-19"

AVG_COLORS = {
    "3년 평균": "#9AA3AF",
    "2년 평균": "#8E7CC3",
    "1년 평균": "#C9A227",
    "6개월 평균": "#B5546B",
    "3개월 평균": "#6C63B5",
    "1개월 평균": "#3B7EA1",
    "1주일 평균": "#2E8B74",
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
    "2년 평균": ("years", 2),
    "1년 평균": ("years", 1),
    "6개월 평균": ("months", 6),
    "3개월 평균": ("months", 3),
    "1개월 평균": ("months", 1),
}


# ---------------------------------------------------------------------------
# 개별 시계열 조회
# ---------------------------------------------------------------------------
묵음_한도일 = 5     # 마지막 자료가 이보다 오래되면 '묵은 자료' 로 봅니다


def _시간제한(함수, 초):
    """함수를 최대 '초' 만큼만 기다립니다.

    ★ FinanceDataReader 는 안에서 requests 를 시간 제한 없이 부릅니다.
      야후가 연결만 받고 응답을 안 주는 날에는 무기한 멈춰서, 아침
      브리핑이 워크플로 시간 한도에 걸렸습니다. 스레드로 돌려 끊습니다.
      (멈춘 스레드는 남지만 스크립트가 끝나면 같이 사라집니다)
    """
    import concurrent.futures as cf
    풀 = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return 풀.submit(함수).result(timeout=초)
    except cf.TimeoutError:
        raise TimeoutError(f"{초}초 안에 응답이 없습니다") from None
    finally:
        풀.shutdown(wait=False)


def _fdr_시리즈(symbol, start, end) -> pd.Series:
    import FinanceDataReader as fdr
    # end 에 하루를 더합니다. FDR 은 날짜만 받아서 실행 기계의 자정으로
    # 자르는데, 한국 PC 에서는 이러면 오늘 장이 통째로 빠집니다.
    끝 = (end + timedelta(days=1)).strftime("%Y-%m-%d")
    data = _시간제한(lambda: fdr.DataReader(
        symbol, start.strftime("%Y-%m-%d"), 끝), 25)
    if data is None or data.empty or "Close" not in data:
        raise ValueError(f"{symbol}: 응답이 비어 있습니다")
    s = pd.to_numeric(data["Close"], errors="coerce").dropna()
    if s.empty:
        raise ValueError(f"{symbol}: 유효한 종가가 없습니다")
    return s.sort_index()


def _야후_시리즈(symbol, start, end) -> pd.Series:
    """야후 차트를 직접 부릅니다. FDR 이 깨진 날의 대체 경로입니다.

    ★ 예전 대체 경로였던 stooq 는 404 를 주다가 이제는 연결조차 안 돼서,
      '경로 네 개' 가 실제로는 FDR 하나뿐이었습니다. FDR 이 실패하면 환율
      5종이 전부 빠졌습니다. 같은 야후라도 FDR 과 다른 주소(query1)·다른
      방식이라 FDR 쪽 문제(라이브러리·pandas 호환)와는 따로 삽니다.
    """
    import json
    import urllib.parse
    import urllib.request
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?period1={int(start.timestamp())}"
           f"&period2={int((end + timedelta(days=1)).timestamp())}&interval=1d")
    요청 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(요청, timeout=15) as resp:
        js = json.loads(resp.read().decode("utf-8"))
    결과 = ((js.get("chart") or {}).get("result") or [None])[0]
    if not 결과 or not 결과.get("timestamp"):
        raise ValueError(f"{symbol}: 야후 응답이 비어 있습니다")
    # 야후 FX 일봉은 런던 자정에 시작합니다. 거래소 시차를 더해 '그 봉의
    # 현지 날짜' 로 붙여야 여름에 하루씩 앞당겨지지 않습니다.
    시차 = int((결과.get("meta") or {}).get("gmtoffset") or 0)
    날짜 = pd.to_datetime([t + 시차 for t in 결과["timestamp"]], unit="s").normalize()
    종가 = (결과.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    s = pd.to_numeric(pd.Series(종가, index=날짜), errors="coerce").dropna()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty:
        raise ValueError(f"{symbol}: 유효한 종가가 없습니다")
    return s.sort_index()


def 묵은날수(시리즈, 오늘=None) -> int:
    """마지막 자료가 오늘보다 며칠 전인지."""
    오늘 = pd.Timestamp(오늘 or datetime.today()).normalize()
    return int((오늘 - pd.Timestamp(시리즈.index.max()).normalize()).days)


def _합성(방법, 시리즈A, 시리즈B) -> pd.Series:
    """두 시계열을 날짜 기준으로 맞춰서 나누거나 곱합니다.

    ★ 두 시계열의 마지막 날이 다르면 공통 마지막 날까지만 씁니다.
      예전에는 ffill 이 먼저 끝난 쪽 값을 끝까지 끌고 가서 '오늘 원화 ÷
      이틀 전 위안' 을 성공으로 돌려줬습니다. 중간 공백은 사흘까지만
      채웁니다(주말·휴일 정도).
    """
    끝 = min(시리즈A.index.max(), 시리즈B.index.max())
    묶음 = pd.concat([시리즈A[시리즈A.index <= 끝].rename("a"),
                    시리즈B[시리즈B.index <= 끝].rename("b")], axis=1)
    묶음 = 묶음.ffill(limit=3).dropna()
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

    def 직접_야후():
        return _야후_시리즈(currency["direct"], start, end)

    def 합성_야후():
        방법, 위, 아래 = cross
        return _합성(방법, _야후_시리즈(위, start, end),
                   _야후_시리즈(아래, start, end))

    경로 = [("직접 조회", 직접_fdr), ("야후 직접", 직접_야후)]
    if cross:
        방법, 위, 아래 = cross
        기호 = "÷" if 방법 == "나누기" else "×"
        경로.append((f"달러 경유 합성 ({위} {기호} {아래})", 합성_fdr))
        경로.append((f"야후 합성 ({위} {기호} {아래})", 합성_야후))

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
            # ★ 조회는 '성공' 인데 몇 주 전에 멈춘 자료가 올 때가 있습니다
            #   (야후가 교차 티커를 죽인 경우 등). 예전에는 날짜를 안 봐서
            #   묵은 환율이 매일 오늘 값처럼 나갔습니다. 묵었으면 다음
            #   경로를 먼저 시도하고, 모두 묵었을 때만 이걸 씁니다.
            묵음 = 묵은날수(시리즈, end)
            if 묵음 > 묵음_한도일:
                기록.append(f"{이름}: 자료가 {묵음}일 묵음")
                아쉬운후보.append((시리즈, 이름, f"{묵음}일 전 자료"))
                continue
            if 충분:
                기록.append(f"{이름}: 성공 ({설명})")
                return _표(시리즈), 이름, 기록
            기록.append(f"{이름}: 자료 부족 — {설명}")
            아쉬운후보.append((시리즈, 이름, 설명))
        except Exception as e:  # noqa: BLE001
            기록.append(f"{이름}: {e}")

    if 아쉬운후보:
        # 완전한 곳이 없으면 그중 가장 이력이 긴 것을 씁니다 (경고와 함께)
        # 덜 묵은 것을 먼저, 그다음 이력이 긴 것
        시리즈, 이름, 설명 = max(
            아쉬운후보, key=lambda x: (-묵은날수(x[0], end), len(x[0])))
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


# ---------------------------------------------------------------------------
# 단기 비교 (1일 전 · 1주일 전)
# ---------------------------------------------------------------------------
#  기간별 '평균' 은 몇 달~몇 년 흐름을 보는 값입니다. 그래서 어제·지난주에
#  비해 올랐는지 내렸는지는 알 수 없습니다. 환전은 며칠 안에 결정하는 일이
#  많으니 단기 비교를 따로 둡니다.
#
#  두 가지를 같이 보여줍니다. 성격이 달라서 하나로 합칠 수 없습니다.
#    · 시점 : 그 날 종가 하나         → "어제 얼마였나"
#    · 평균 : 그 기간의 평균          → "지난 한 주 수준이 어땠나"
#
#  주말·공휴일에는 종가가 없습니다. 그래서 '그 날짜 이하의 마지막 값' 을
#  씁니다. 예를 들어 오늘이 월요일이면 '1일 전' 은 지난 금요일 종가입니다.
#  실제로 며칠 전 값을 썼는지는 설명에 적어 돌려줍니다.
#
#  변동률의 부호는 '원화 부담' 기준으로 읽으시면 됩니다.
#    + 면 그때보다 원화가 더 든다(= 환전이 비싸졌다)
#    − 면 그때보다 원화가 덜 든다(= 환전이 싸졌다)

단기_시점_정의 = {
    "1일 전": 1,
    "1주일 전": 7,
}

단기_평균_정의 = {
    "1주일 평균": 7,
}


def 시점_값(data: pd.DataFrame, 일수전: int):
    """최신일에서 일수전 만큼 뒤로 간 시점의 종가. (기준일, 값) 또는 None.

    그 날짜에 종가가 없으면(주말·공휴일) 그 이전의 마지막 값을 씁니다.
    """
    if data is None or data.empty:
        return None
    최신 = data.index.max()
    목표 = 최신 - pd.Timedelta(days=int(일수전))
    구간 = data.loc[data.index <= 목표, "Close"]
    if 구간.empty:
        return None
    return 구간.index[-1], float(구간.iloc[-1])


def 단기_요약(data: pd.DataFrame) -> list:
    """최신 종가를 어제·지난주와 견줍니다.

    [{종류, 라벨, 신뢰, 기준일, 값, 차이, 변동률, 설명}] 를 순서대로 돌려줍니다.
      종류 = "시점" (그 날 종가) 또는 "평균" (그 기간 평균)
      신뢰 = False 면 값·차이·변동률이 없고 설명만 있습니다.
    """
    if data is None or data.empty:
        return []
    현재가 = float(data["Close"].iloc[-1])
    최신 = data.index.max()
    결과 = []

    for 라벨, 일수 in 단기_시점_정의.items():
        찾음 = 시점_값(data, 일수)
        if 찾음 is None:
            결과.append({"종류": "시점", "라벨": 라벨, "신뢰": False,
                       "설명": "그 시점 자료가 없습니다"})
            continue
        기준일, 값 = 찾음
        실제일수 = (최신 - 기준일).days
        결과.append({
            "종류": "시점", "라벨": 라벨, "신뢰": True,
            "기준일": 기준일, "값": 값,
            "차이": 현재가 - 값,
            "변동률": ((현재가 - 값) / 값 * 100) if 값 else 0.0,
            "설명": (f"{기준일:%m월 %d일} 종가"
                   + (f" · 실제 {실제일수}일 전" if 실제일수 != 일수 else "")),
        })

    for 라벨, 일수 in 단기_평균_정의.items():
        시작 = 최신 - pd.Timedelta(days=int(일수) - 1)
        구간 = data.loc[data.index >= 시작, "Close"]
        if len(구간) < 2:
            결과.append({"종류": "평균", "라벨": 라벨, "신뢰": False,
                       "설명": f"이 기간 자료가 {len(구간)}개뿐"})
            continue
        값 = float(구간.mean())
        결과.append({
            "종류": "평균", "라벨": 라벨, "신뢰": True,
            "기준일": 구간.index[0], "값": 값,
            "차이": 현재가 - 값,
            "변동률": ((현재가 - 값) / 값 * 100) if 값 else 0.0,
            "설명": (f"{구간.index[0]:%m/%d}~{최신:%m/%d} "
                   f"영업일 {len(구간)}일 평균"),
        })
    return 결과


def 단기_메시지(요약: list) -> tuple:
    """단기 흐름을 한 줄 문장으로. (st 함수 이름, 문장) 을 돌려줍니다.

    기준은 '1주일 전' 입니다. 하루 등락은 잡음이 많아서 방향을 정하기에
    부족합니다. 1주일 자료가 없으면 1일 전으로 대신합니다.
    """
    시점 = {r["라벨"]: r for r in 요약
          if r["종류"] == "시점" and r.get("신뢰")}
    하루, 주 = 시점.get("1일 전"), 시점.get("1주일 전")
    if not 하루 and not 주:
        return "info", "단기 비교에 쓸 최근 자료가 부족해요."

    조각 = []
    for 이름, r in (("어제", 하루), ("지난주", 주)):
        if not r:
            continue
        방향 = "올랐" if r["변동률"] > 0 else ("내렸" if r["변동률"] < 0 else "같")
        if 방향 == "같":
            조각.append(f"{이름}와 거의 같아요")
        else:
            조각.append(f"{이름}보다 {abs(r['변동률']):.2f}% {방향}어요")
    문장 = " · ".join(조각)

    기준 = (주 or 하루)["변동률"]
    if 기준 <= -0.5:
        return "success", f"{문장}. 최근 며칠 사이 원화 부담이 줄었어요."
    if 기준 >= 0.5:
        return "warning", f"{문장}. 최근 며칠 사이 원화 부담이 늘었어요."
    return "info", f"{문장}. 단기 움직임은 크지 않아요."


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


# ---------------------------------------------------------------------------
# 텔레그램 요약 — 매일 자동 발송 / 환전 페이지 버튼에서 함께 씁니다
# ---------------------------------------------------------------------------
#  ★ 이 아래는 streamlit 을 쓰지 않습니다. GitHub Actions 스크립트에서도
#    그대로 가져다 쓰기 때문입니다. (호텔 가격 알림과 같은 이유)

_평균_표시순서 = ["1개월 평균", "3개월 평균", "6개월 평균",
              "1년 평균", "2년 평균", "3년 평균"]


def 범위_위치(data: pd.DataFrame, years: float = 1.0) -> dict:
    """최근 N년 범위에서 지금이 어디쯤인지.

    돌려주는 것: {최저, 최고, 현재, 퍼센타일, 자료수}
      퍼센타일 = 0 이면 그 기간 최저, 100 이면 최고.

    ★ '평균 대비 몇 %' 보다 이게 직관적입니다. 평균 대비 -3% 라고 하면
      그게 싼 건지 감이 안 오지만, "1년 범위에서 아래쪽 12% 지점" 은
      바로 와닿습니다. 평균은 한쪽으로 치우친 분포에서 오해를 부르기도
      합니다.
    """
    빈값 = {"최저": 0.0, "최고": 0.0, "현재": 0.0, "퍼센타일": None, "자료수": 0}
    if data is None or data.empty or "Close" not in data:
        return 빈값
    끝 = data.index.max()
    구간 = data.loc[data.index >= 끝 - pd.Timedelta(days=int(365 * years)), "Close"]
    구간 = pd.to_numeric(구간, errors="coerce").dropna()
    if len(구간) < 30:                      # 자료가 너무 적으면 위치가 무의미
        return 빈값
    최저, 최고 = float(구간.min()), float(구간.max())
    현재 = float(구간.iloc[-1])
    폭 = 최고 - 최저
    return {
        "최저": 최저, "최고": 최고, "현재": 현재,
        "퍼센타일": ((현재 - 최저) / 폭 * 100) if 폭 > 0 else 50.0,
        "자료수": len(구간),
    }


def 구간_이름(퍼센타일) -> str:
    """퍼센타일을 사람 말로. 환전하는 사람 기준(낮을수록 유리)입니다."""
    if 퍼센타일 is None:
        return ""
    if 퍼센타일 <= 15:
        return "싼 편"
    if 퍼센타일 <= 35:
        return "다소 싼 편"
    if 퍼센타일 < 65:
        return "보통"
    if 퍼센타일 < 85:
        return "다소 비싼 편"
    return "비싼 편"


def 범위_막대(퍼센타일, 칸수: int = 14) -> str:
    """1,290 ──●──────── 1,480 처럼 위치를 눈으로 보여주는 막대."""
    if 퍼센타일 is None:
        return ""
    자리 = int(round(min(max(퍼센타일, 0), 100) / 100 * (칸수 - 1)))
    return "─" * 자리 + "●" + "─" * (칸수 - 1 - 자리)


def 체감_환산(현재가: float, currency: dict, 원화: float = 1_000_000) -> str:
    """"100만원 → $743" 처럼 실제로 손에 쥐는 금액으로 바꿔 줍니다.

    ★ 환율 1,346원이 1,338원이 됐다는 말은 체감이 안 됩니다. 같은 돈으로
      얼마를 더 받는지로 바꾸면 바로 와닿습니다.
    """
    현재가 = float(현재가 or 0)
    if 현재가 <= 0:
        return ""
    # quote 는 "1달러"·"100엔" 처럼 **몇 단위 기준인지**를 담은 라벨입니다.
    # 앞의 숫자를 떼어 내야 "114,810엔" 같은 표기가 됩니다.
    단위 = re.sub(r"^[\d,]+\s*", "", str(currency.get("quote") or "")).strip()
    배수 = float(currency.get("scale") or 1)       # 엔은 100엔 기준이라 100
    받는돈 = 원화 / 현재가 * 배수
    자릿수 = 0 if 받는돈 >= 100 else (1 if 받는돈 >= 10 else 2)
    return f"{받는돈:,.{자릿수}f}{단위}"


def _차이표시(차이, 기준값, 단위="원") -> str:
    """차액을 부호와 함께 적습니다 (예: "-4원", "+12.35원").

    ★ 소수 자릿수는 **차액이 아니라 환율 자체**의 크기로 정합니다.
      차액만 보고 정하면 달러는 "-4원", 위안은 "-6.3400원" 처럼
      자릿수가 들쭉날쭉해집니다.
    """
    자릿수 = 0 if abs(기준값) >= 500 else (2 if abs(기준값) >= 50 else 4)
    부호 = "+" if 차이 > 0 else ""
    return f"{부호}{차이:,.{자릿수}f}{단위}"


def 텔레그램_통화요약(이름: str, currency: dict, data, 평균: dict,
                신뢰: dict, 단기: list) -> str:
    """통화 하나의 상태를 텔레그램용 몇 줄로 정리합니다."""
    현재가 = float(data["Close"].iloc[-1])
    최신일 = data.index.max()
    단기표 = {r["라벨"]: r for r in 단기}

    줄 = [f"💱 <b>{이름}</b>",
        f"　{금액표시(현재가, currency['unit'])} "
        f"({currency['quote']} 기준, {최신일:%m/%d} 종가)"]

    조각 = []
    for 라벨, 짧은 in (("1일 전", "어제"), ("1주일 전", "지난주")):
        r = 단기표.get(라벨)
        if not r or not r.get("신뢰"):
            continue
        v = r["변동률"]
        화살 = "▲" if v > 0.05 else ("▼" if v < -0.05 else "―")
        조각.append(f"{짧은} 대비 {화살}{abs(v):.2f}% "
                  f"({_차이표시(r['차이'], 현재가, currency['unit'])})")
    if 조각:
        줄.append("　" + " · ".join(조각))

    평균줄 = []
    for 라벨 in _평균_표시순서:
        if not 신뢰.get(라벨):
            continue
        값 = 평균.get(라벨)
        if 값 != 값 or not 값:                     # NaN 이거나 0
            continue
        차이 = 현재가 - 값
        차이율 = 차이 / 값 * 100
        화살 = "▲" if 차이율 > 0.05 else ("▼" if 차이율 < -0.05 else "―")
        줄이름 = 라벨.replace(" 평균", "")
        평균줄.append(f"{줄이름} {화살}{abs(차이율):.1f}% "
                   f"({_차이표시(차이, 현재가, currency['unit'])})")
    if 평균줄:
        # ★ 퍼센트에 금액까지 붙으면 한 줄이 너무 길어져 휴대폰에서 줄이
        #   제멋대로 접힙니다. 두 개씩 끊어 적습니다.
        줄.append("　평균 대비")
        for i in range(0, len(평균줄), 2):
            줄.append("　　" + " / ".join(평균줄[i:i + 2]))

    return "\n".join(줄)


def 텔레그램_전체요약(통화목록=None, years: int = 3) -> tuple:
    """(본문, 실패목록). 실패목록 = [(통화이름, 오류문장), …]

    통화목록 을 안 주면 CURRENCIES 의 전체 통화를 다 봅니다.
    하나가 실패해도 나머지는 계속 진행하고, 실패한 것만 맨 아래
    한 줄로 모아 알려줍니다 — 환율 하나 못 가져왔다고 전체를
    조용히 안 보내면 그게 더 나쁩니다.
    """
    이름목록 = list(통화목록) if 통화목록 else list(CURRENCIES)
    줄 = [f"💱 <b>오늘의 환율</b> ({datetime.today():%Y-%m-%d})"]
    실패 = []
    for 이름 in 이름목록:
        cur = CURRENCIES.get(이름)
        if not cur:
            실패.append((이름, "모르는 통화입니다"))
            continue
        try:
            data, _출처, _기록 = 환율_가져오기(cur, years=years)
            평균, 신뢰 = 평균_계산(data)
            단기 = 단기_요약(data)
            # ★ 문장 만드는 것도 try 안에 둡니다. 자료가 비어 있으면
            #   data["Close"].iloc[-1] 에서 터지는데, 이게 try 밖에 있으면
            #   통화 하나 때문에 그날 요약 전체가 안 나갑니다.
            한통화 = 텔레그램_통화요약(이름, cur, data, 평균, 신뢰, 단기)
        except Exception as e:                               # noqa: BLE001
            실패.append((이름, str(e)))
            continue
        줄.append("")
        줄.append(한통화)

    if 실패:
        줄.append("")
        줄.append("⚠️ 못 가져온 통화: " + ", ".join(n for n, _e in 실패))

    return "\n".join(줄), 실패


def 타이밍_메시지(저렴한_구간수: int) -> tuple:
    if 저렴한_구간수 >= 4:
        return "success", "과거 평균 대비 낮은 편이에요. 환전하기 나쁘지 않은 시점일 수 있어요."
    if 저렴한_구간수 <= 1:
        return "warning", "과거 평균 대비 높은 편이에요. 나눠서 환전하거나 조금 더 지켜보는 방법도 있어요."
    return "info", "과거 평균과 비슷한 수준이에요. 필요한 금액과 시점을 함께 고려해 보세요."
