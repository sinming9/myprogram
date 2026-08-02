"""
==========================================================================
달걀 모형(코스톨라니 달걀) 금리 사이클 엔진
==========================================================================
업로드해 주신 egg_cycle.py 에서 계산 로직만 옮긴 것입니다.

바꾼 것
  · matplotlib / PyQt 부분 제거 → 화면은 pages/5_🥚_금리_사이클.py 에서 plotly 로 그립니다.
    (Streamlit Cloud 리눅스 서버에는 한글 폰트가 없어서 matplotlib 로 그리면
     글자가 전부 네모로 깨집니다. plotly 는 브라우저가 글자를 그려서 문제없습니다.)
  · 파일 캐시(DailyCache) 제거 → Streamlit 의 st.cache_data 로 대체
  · 달걀 곡선 좌표를 내주는 함수 추가 (egg_outline, point_at)

계산 결과는 원본과 동일합니다.
==========================================================================
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

모듈버전 = "2026-08-02h"

# ---------------------------------------------------------------------------
# 1. 사이클 정의 (A~F 6개 국면)
#    r = 정규화 금리수준 (0 = 사이클 저점 D, 1 = 사이클 고점 A)
#    side = "up"(금리 상승 = 호황기, 달걀 왼쪽) / "down"(금리 하락 = 불황기, 오른쪽)
# ---------------------------------------------------------------------------
R_MID_LOW = 0.28     # E, C 지점의 금리수준
R_MID_HIGH = 0.72    # F, B 지점의 금리수준


@dataclass(frozen=True)
class Phase:
    code: str
    name: str
    regime: str
    action: str
    note: str


PHASES: Dict[str, Phase] = {
    "D":   Phase("D",   "금리 저점 (D)",          "전환점",
                 "부동산 매도 → 주식 매수 준비", "인하 사이클 종료. 완화 효과가 실물에 도달하는 구간."),
    "D-E": Phase("D-E", "상승 초기 (D→E)",        "호황기",
                 "주식 비중 확대 / 부동산 축소",   "첫 인상 직후. 이론상 주식 비중을 늘리는 구간."),
    "E":   Phase("E",   "주식 매수 구간 (E)",      "호황기",
                 "주식 투자 / 부동산 매도",       "경기 확장이 확인되는 시점."),
    "E-F": Phase("E-F", "호황 진행 (E→F)",        "호황기",
                 "주식 보유 → 단계적 차익 실현",   "연속 인상 국면. 상승 후반으로 갈수록 비중 축소."),
    "F":   Phase("F",   "주식 매도 구간 (F)",      "호황기",
                 "주식 매도 / 예금 입금",         "금리 정점이 가까워지는 과열 구간."),
    "F-A": Phase("F-A", "정점 접근 (F→A)",        "호황기",
                 "예금 이동 완료 / 채권 매수 준비", "최종금리 논의가 나오는 구간."),
    "A":   Phase("A",   "금리 정점 (A)",          "전환점",
                 "예금 → 장기채 전환",           "인상 사이클 종료. 채권 듀레이션을 늘리는 시점."),
    "A-B": Phase("A-B", "하락 초기 (A→B)",        "불황기",
                 "예금 인출 → 채권 투자",         "첫 인하 직후. 채권 가격 상승 국면."),
    "B":   Phase("B",   "채권 투자 구간 (B)",      "불황기",
                 "예금 인출 / 채권 투자",         "경기 둔화가 지표로 확인되는 시점."),
    "B-C": Phase("B-C", "침체 진행 (B→C)",        "불황기",
                 "채권 보유 / 현금 확보",         "연속 인하 국면."),
    "C":   Phase("C",   "부동산 매수 구간 (C)",    "불황기",
                 "채권 매도 / 부동산 투자",       "저금리로 조달비용이 낮아지는 시점."),
    "C-D": Phase("C-D", "저점 접근 (C→D)",        "불황기",
                 "부동산 비중 확대 / 주식 관망",   "인하 사이클 막바지."),
}

# 달걀 위 6개 기준점: (코드, r, side, 라벨)
MARKERS: List[Tuple[str, float, str, str]] = [
    ("A", 1.00,        "top",  "금리정점"),
    ("B", R_MID_HIGH,  "down", "예금인출 / 채권투자"),
    ("C", R_MID_LOW,   "down", "부동산투자 / 채권매도"),
    ("D", 0.00,        "bot",  "금리저점"),
    ("E", R_MID_LOW,   "up",   "주식투자 / 부동산매도"),
    ("F", R_MID_HIGH,  "up",   "예금입금 / 주식매도"),
]


# ---------------------------------------------------------------------------
# 2. 설정 / 상태
# ---------------------------------------------------------------------------
@dataclass
class CycleConfig:
    """사이클 저점·고점 기준. 미지정 시 과거 이력에서 자동 산출."""
    country: str = "KR"
    cycle_low: Optional[float] = None
    cycle_high: Optional[float] = None
    lookback_years: int = 3
    hold_days_for_plateau: int = 150

    def label(self) -> str:
        return {"KR": "한국 (한국은행 기준금리)",
                "US": "미국 (연방기금금리 상단)"}.get(self.country, self.country)


@dataclass
class RateHistory:
    """(날짜, 금리) 시계열. 오름차순 정렬 가정."""
    points: List[Tuple[date, float]] = field(default_factory=list)

    def sort(self) -> "RateHistory":
        self.points.sort(key=lambda p: p[0])
        return self

    @property
    def latest(self) -> Tuple[date, float]:
        return self.points[-1]

    def window(self, years: int) -> List[Tuple[date, float]]:
        """최근 N년 구간. 구간 시작 시점에 유효했던 값(직전 값)도 포함."""
        cutoff = self.latest[0] - timedelta(days=365 * years)
        inside = [p for p in self.points if p[0] >= cutoff]
        before = [p for p in self.points if p[0] < cutoff]
        if before:
            inside.insert(0, (cutoff, before[-1][1]))
        return inside or list(self.points)

    def last_change(self) -> Tuple[Optional[date], float]:
        """(마지막 변경일, 변화폭). 변화가 없으면 (None, 0.0)."""
        pts = self.points
        if len(pts) < 2:
            return None, 0.0
        current = pts[-1][1]
        for i in range(len(pts) - 1, 0, -1):
            prev = pts[i - 1][1]
            if abs(prev - current) > 1e-9:
                return pts[i][0], round(current - prev, 4)
        return None, 0.0

    def 계단_시계열(self):
        """차트용. 금리는 다음 변경일까지 유지되므로 계단식으로 펼칩니다."""
        날짜 = [d for d, _ in self.points]
        값 = [v for _, v in self.points]
        return 날짜, 값


@dataclass
class CycleState:
    country: str
    as_of: date
    rate: float
    cycle_low: float
    cycle_high: float
    r: float
    side: str
    direction: str
    phase: Phase
    angle_deg: float
    last_change_date: Optional[date]
    last_change_bp: float
    days_since_change: Optional[int]
    plateau: bool
    source: str

    def summary(self) -> str:
        arrow = {"인상": "▲", "인하": "▼", "동결": "―"}[self.direction]
        return (f"[{self.country}] {self.rate:.2f}% {arrow} {self.direction}  |  "
                f"{self.phase.name} · {self.phase.regime}  |  "
                f"사이클 위치 {self.r * 100:.0f}%  |  {self.phase.action}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["last_change_date"] = (self.last_change_date.isoformat()
                                 if self.last_change_date else None)
        d["phase"] = asdict(self.phase)
        return d


# ---------------------------------------------------------------------------
# 3. 위치 계산
# ---------------------------------------------------------------------------
def _phase_for(r: float, side: str) -> Phase:
    eps = 0.02
    if r >= 1 - eps:
        return PHASES["A"]
    if r <= eps:
        return PHASES["D"]
    if side == "up":
        if r < R_MID_LOW - eps:
            return PHASES["D-E"]
        if abs(r - R_MID_LOW) <= eps:
            return PHASES["E"]
        if r < R_MID_HIGH - eps:
            return PHASES["E-F"]
        if abs(r - R_MID_HIGH) <= eps:
            return PHASES["F"]
        return PHASES["F-A"]
    if r > R_MID_HIGH + eps:
        return PHASES["A-B"]
    if abs(r - R_MID_HIGH) <= eps:
        return PHASES["B"]
    if r > R_MID_LOW + eps:
        return PHASES["B-C"]
    if abs(r - R_MID_LOW) <= eps:
        return PHASES["C"]
    return PHASES["C-D"]


def angle_for(r: float, side: str) -> float:
    """정규화 금리수준 r 과 방향으로 달걀 위 각도(deg).
    위(90°) = A 금리정점, 아래(270°) = D 금리저점,
    왼쪽 반원 = 상승(호황기), 오른쪽 반원 = 하락(불황기)."""
    r = min(max(r, 0.0), 1.0)
    if side == "up":
        return 270.0 - 180.0 * r
    return -90.0 + 180.0 * r


def marker_angle(r: float, side: str) -> float:
    """MARKERS 의 side 값('top'/'bot' 포함)을 각도로."""
    if side == "top":
        return 90.0
    if side == "bot":
        return -90.0
    return angle_for(r, side)


def compute_state(history: RateHistory, config: CycleConfig,
                  source: str = "manual") -> CycleState:
    history.sort()
    as_of, rate = history.latest

    win = history.window(config.lookback_years)
    lo = config.cycle_low if config.cycle_low is not None else min(v for _, v in win)
    hi = config.cycle_high if config.cycle_high is not None else max(v for _, v in win)
    if hi - lo < 1e-6:
        hi, lo = lo + 1.0, lo
    lo, hi = min(lo, rate), max(hi, rate)

    r = (rate - lo) / (hi - lo)

    change_date, change = history.last_change()
    days = (as_of - change_date).days if change_date else None
    if change > 0:
        direction, side = "인상", "up"
    elif change < 0:
        direction, side = "인하", "down"
    else:
        direction, side = "동결", "up"

    plateau = bool(days is not None and days >= config.hold_days_for_plateau)
    if plateau:
        direction = "동결"

    return CycleState(
        country=config.country, as_of=as_of, rate=rate,
        cycle_low=round(lo, 4), cycle_high=round(hi, 4),
        r=round(r, 4), side=side, direction=direction,
        phase=_phase_for(r, side), angle_deg=angle_for(r, side),
        last_change_date=change_date, last_change_bp=round(change * 100, 1),
        days_since_change=days, plateau=plateau, source=source,
    )


# ---------------------------------------------------------------------------
# 4. 달걀 곡선 좌표 (plotly 용)
# ---------------------------------------------------------------------------
EGG_A, EGG_B, EGG_TAPER = 1.00, 1.30, 0.07


def point_at(deg):
    """각도(deg) 하나에 대한 달걀 위 좌표 (x, y)."""
    t = np.radians(deg)
    x = EGG_A * np.cos(t) * (1 - EGG_TAPER * np.sin(t))
    y = EGG_B * np.sin(t)
    return float(x), float(y)


def egg_outline(시작=-90, 끝=270, 개수=361):
    """달걀 윤곽선 좌표 배열 (xs, ys)."""
    각도 = np.linspace(시작, 끝, 개수)
    t = np.radians(각도)
    xs = EGG_A * np.cos(t) * (1 - EGG_TAPER * np.sin(t))
    ys = EGG_B * np.sin(t)
    return xs.tolist(), ys.tolist()


# ---------------------------------------------------------------------------
# 5. 데이터 조회
# ---------------------------------------------------------------------------
class RateFetchError(RuntimeError):
    pass


def fetch_bok_base_rate(api_key: str, years: int = 5, timeout: int = 10) -> RateHistory:
    """한국은행 ECOS: 722Y001 / 0101000 = 한국은행 기준금리 (일별)."""
    import json
    import urllib.request
    end = date.today()
    start = end - timedelta(days=365 * years)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/"
           f"1/10000/722Y001/D/{start:%Y%m%d}/{end:%Y%m%d}/0101000")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        js = json.loads(resp.read().decode("utf-8"))
    rows = js.get("StatisticSearch", {}).get("row")
    if not rows:
        raise RateFetchError(f"ECOS 응답에 데이터가 없습니다: {json.dumps(js, ensure_ascii=False)[:200]}")
    pts = [(datetime.strptime(r["TIME"], "%Y%m%d").date(), float(r["DATA_VALUE"]))
           for r in rows if r.get("DATA_VALUE") not in (None, "")]
    return RateHistory(pts).sort()


def fetch_fed_funds_upper(api_key: str, years: int = 5, timeout: int = 10) -> RateHistory:
    """FRED: DFEDTARU = 연방기금금리 목표범위 상단 (일별)."""
    import json
    import urllib.request
    start = date.today() - timedelta(days=365 * years)
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id=DFEDTARU&api_key={api_key}&file_type=json"
           f"&observation_start={start:%Y-%m-%d}")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        js = json.loads(resp.read().decode("utf-8"))
    obs = js.get("observations")
    if not obs:
        raise RateFetchError(f"FRED 응답에 데이터가 없습니다: {json.dumps(js)[:200]}")
    pts = [(datetime.strptime(o["date"], "%Y-%m-%d").date(), float(o["value"]))
           for o in obs if o["value"] not in (".", "", None)]
    return RateHistory(pts).sort()


# 조회 실패 시 쓰는 기본값.
#  ※ 새 금리 결정이 나오면 아래 줄만 추가하면 됩니다. 화면에서도 직접 넣을 수 있습니다.
FALLBACK_HISTORY: Dict[str, List[Tuple[str, float]]] = {
    "KR": [("2023-01-13", 3.50), ("2024-10-11", 3.25), ("2024-11-28", 3.00),
           ("2025-02-25", 2.75), ("2025-05-29", 2.50), ("2026-07-16", 2.75)],
    "US": [("2023-07-27", 5.50), ("2024-09-19", 5.00), ("2024-11-08", 4.75),
           ("2024-12-19", 4.50), ("2025-09-18", 4.25), ("2025-10-29", 4.00),
           ("2025-12-10", 3.75)],
}


def fallback_history(country: str, 추가목록=None) -> RateHistory:
    """기본 이력 + 사용자가 화면에서 추가한 이력."""
    기본 = FALLBACK_HISTORY.get(country, FALLBACK_HISTORY["KR"])
    pts = [(datetime.strptime(d, "%Y-%m-%d").date(), float(v)) for d, v in 기본]
    for d, v in (추가목록 or []):
        if isinstance(d, str):
            d = datetime.strptime(d[:10], "%Y-%m-%d").date()
        pts.append((d, float(v)))
    pts.sort(key=lambda p: p[0])
    # 중복 날짜는 뒤엣것(사용자 입력)을 우선
    정리 = {}
    for d, v in pts:
        정리[d] = v
    pts = sorted(정리.items())
    if pts and pts[-1][0] < date.today():
        pts.append((date.today(), pts[-1][1]))   # 오늘까지 같은 수준 유지로 간주
    return RateHistory(pts).sort()


def 이력_불러오기(country: str, api_key: Optional[str], 추가목록=None):
    """(RateHistory, 출처, 오류메시지) 반환. 실패해도 예외를 던지지 않습니다."""
    if api_key:
        try:
            if country == "KR":
                return fetch_bok_base_rate(api_key), "ECOS (한국은행)", None
            return fetch_fed_funds_upper(api_key), "FRED (세인트루이스 연준)", None
        except Exception as e:  # noqa: BLE001
            오류 = f"{type(e).__name__}: {e}"
            return fallback_history(country, 추가목록), "내장 기본값", 오류
    return fallback_history(country, 추가목록), "내장 기본값", None
