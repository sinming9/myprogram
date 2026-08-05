"""
==========================================================================
금리 결정 확률 엔진 (FedWatch 방식 직접 계산)
==========================================================================
CME FedWatch 는 무료 API 가 없습니다. 대신 그 도구가 쓰는 원본 데이터인
30일 연방기금 선물(ZQ)을 직접 받아서 같은 공식으로 계산합니다.

원리
  ZQ 계약은 "100 - 그 달의 일평균 실효 연방기금금리" 로 정산됩니다.
    예) 2026년 4월물 96.36  →  시장이 보는 4월 평균 금리 = 3.64%

  회의가 그 달 중간에 있으면 평균은 두 구간의 가중평균입니다.
    평균금리 = (회의전 일수/전체일수) x 현재금리
             + (회의후 일수/전체일수) x 회의후금리

  여기서 '회의후금리' 를 역산하고, 현재금리와의 차이를 0.25%p 로 나누면
  25bp 움직임이 가격에 얼마나 반영됐는지(=확률)가 나옵니다.

한계 (반드시 알고 쓰세요)
  · CME 는 여러 회의를 묶어 확률 트리를 만듭니다. 여기서는 "다음 회의 한 번"
    만 계산합니다. 다음 회의는 CME 값과 거의 같지만, 그 다음 회의부터는
    차이가 벌어집니다.
  · 50bp 움직임이 섞이면 단순 계산으로는 구분되지 않습니다.
  · 선물 가격은 실제 확률이 아니라 '위험을 감안한 가격' 입니다.

한국은행은 이런 선물시장이 없어서 확률을 계산할 수 없습니다.
회의 일정과 직전 결정만 보여줍니다.
==========================================================================
"""

import calendar
import json
import urllib.parse
import urllib.request
from datetime import date, datetime

모듈버전 = "2026-08-05"

# ---------------------------------------------------------------------------
# 회의 일정
#   ※ 해가 바뀌면 여기에 새 일정을 넣으세요. 화면에서도 확인할 수 있습니다.
# ---------------------------------------------------------------------------
FOMC_일정 = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 11, 4), date(2026, 12, 16),
]

금통위_일정 = [
    date(2026, 1, 15), date(2026, 2, 26), date(2026, 4, 10), date(2026, 5, 28),
    date(2026, 7, 16), date(2026, 8, 27), date(2026, 10, 22), date(2026, 11, 26),
]

월코드 = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
        7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}


def 다음_회의(일정, 오늘=None):
    오늘 = 오늘 or date.today()
    남은 = [d for d in 일정 if d >= 오늘]
    return 남은[0] if 남은 else None


def 남은_회의들(일정, 오늘=None, 개수=4):
    오늘 = 오늘 or date.today()
    return [d for d in 일정 if d >= 오늘][:개수]


# ---------------------------------------------------------------------------
# 시세 조회
# ---------------------------------------------------------------------------
def _야후_최근종가(티커: str, 시간제한=15) -> float:
    """야후 파이낸스 차트 API 에서 최근 종가 하나."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(티커)}?range=1mo&interval=1d")
    요청 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(요청, timeout=시간제한) as resp:
        js = json.loads(resp.read().decode("utf-8"))
    결과 = (js.get("chart") or {}).get("result")
    if not 결과:
        raise ValueError(f"{티커}: 응답에 데이터가 없습니다")
    종가들 = 결과[0]["indicators"]["quote"][0].get("close") or []
    유효 = [v for v in 종가들 if v is not None]
    if not 유효:
        raise ValueError(f"{티커}: 유효한 종가가 없습니다")
    return float(유효[-1])


def ZQ_가격(회의일: date):
    """회의가 있는 달의 ZQ 선물 가격. (가격, 사용한티커) 반환."""
    후보 = [
        f"ZQ{월코드[회의일.month]}{회의일.year % 100:02d}.CBT",
        f"ZQ{월코드[회의일.month]}{회의일.year % 100:02d}",
    ]
    오류 = []
    for 티커 in 후보:
        try:
            return _야후_최근종가(티커), 티커
        except Exception as e:  # noqa: BLE001
            오류.append(f"{티커}: {e}")
    raise RuntimeError(" / ".join(오류))


def 실효금리_FRED(api_key: str = None, 시간제한=15) -> float:
    """FRED DFF (일별 실효 연방기금금리). 키가 없으면 예외."""
    if not api_key:
        raise ValueError("FRED API 키가 없습니다")
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id=DFF&api_key={api_key}&file_type=json"
           "&sort_order=desc&limit=5")
    with urllib.request.urlopen(url, timeout=시간제한) as resp:
        js = json.loads(resp.read().decode("utf-8"))
    for o in js.get("observations", []):
        if o["value"] not in (".", "", None):
            return float(o["value"])
    raise ValueError("FRED DFF 응답에 값이 없습니다")


# ---------------------------------------------------------------------------
# 확률 계산
# ---------------------------------------------------------------------------
def 확률_계산(회의일: date, 현재_실효금리: float, 계약가: float, 단위=0.25) -> dict:
    """FedWatch 와 같은 일수가중 방식으로 다음 회의의 움직임 확률을 계산.

    반환: {"평균금리","회의후금리","변화폭","방향","확률","전체일수","회의후일수"}
    """
    전체일수 = calendar.monthrange(회의일.year, 회의일.month)[1]
    회의후일수 = 전체일수 - 회의일.day
    평균금리 = 100.0 - float(계약가)

    if 회의후일수 <= 0:
        # 회의가 월말이면 그 달 평균으로는 판별이 안 됩니다
        회의후금리 = 평균금리
    else:
        앞비중 = 회의일.day / 전체일수
        회의후금리 = (평균금리 - 앞비중 * 현재_실효금리) * 전체일수 / 회의후일수

    변화폭 = 회의후금리 - 현재_실효금리
    확률 = min(max(abs(변화폭) / 단위, 0.0), 1.0)
    if abs(변화폭) < 0.01:
        방향 = "동결"
    elif 변화폭 > 0:
        방향 = "인상"
    else:
        방향 = "인하"

    return {
        "평균금리": round(평균금리, 4),
        "회의후금리": round(회의후금리, 4),
        "변화폭": round(변화폭, 4),
        "변화폭bp": round(변화폭 * 100, 1),
        "방향": 방향,
        "확률": round(확률, 4),
        "동결확률": round(1 - 확률, 4),
        "전체일수": 전체일수,
        "회의후일수": 회의후일수,
    }


def 실효금리_추정(목표상단: float) -> float:
    """FRED 를 못 쓸 때. 실효금리는 목표범위 상단보다 보통 7~9bp 낮습니다."""
    return round(목표상단 - 0.08, 4)


def 미국_전망(현재_실효금리=None, fred_key=None, 오늘=None, 목표상단=None):
    """(결과dict 또는 None, 기록리스트)

    현재_실효금리를 정하는 순서
      1) 인자로 직접 받은 값
      2) FRED DFF (키가 있을 때)
      3) 목표범위 상단 - 8bp 로 추정 (키가 없어도 동작)
    """
    기록 = []
    회의일 = 다음_회의(FOMC_일정, 오늘)
    if 회의일 is None:
        return None, ["남은 FOMC 일정이 없습니다. engines/fedwatch.py 의 FOMC_일정 을 갱신하세요."]

    if 현재_실효금리 is None:
        try:
            현재_실효금리 = 실효금리_FRED(fred_key)
            기록.append(f"실효금리: FRED DFF {현재_실효금리:.2f}%")
        except Exception as e:  # noqa: BLE001
            기록.append(f"FRED 조회 안 됨 ({e})")
            if 목표상단 is None:
                기록.append("목표범위도 모릅니다. 확률을 계산할 수 없습니다.")
                return None, 기록
            현재_실효금리 = 실효금리_추정(목표상단)
            기록.append(f"실효금리: 목표상단 {목표상단:.2f}% - 8bp = {현재_실효금리:.2f}% (추정)")

    try:
        가격, 티커 = ZQ_가격(회의일)
        기록.append(f"선물: {티커} = {가격:.4f}")
    except Exception as e:  # noqa: BLE001
        기록.append(f"선물 조회 실패 ({e})")
        return None, 기록

    결과 = 확률_계산(회의일, 현재_실효금리, 가격)
    결과["회의일"] = 회의일
    결과["현재금리"] = 현재_실효금리
    결과["티커"] = 티커
    기록.append(f"계산: {결과['방향']} 확률 {결과['확률'] * 100:.1f}%")
    return 결과, 기록
