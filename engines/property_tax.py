"""
==========================================================================
재산세(7월·9월) + 종합부동산세(12월) 계산 엔진
==========================================================================
property_tax_calculator_gui.py (tkinter 버전)의 계산 로직만 그대로 옮긴 것입니다.
화면 코드(tkinter)는 제거하고, 계산 함수만 남겨서 Streamlit에서 씁니다.

세법이 바뀌면 아래 세율표만 수정하면 됩니다.
==========================================================================
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# =========================================================
# 세율표
# =========================================================

RATE_PROP_SPECIAL: List[Tuple[float, float, float]] = [   # 재산세 특례세율 (1세대1주택, 공시 9억 이하)
    (0,           0.0005, 0),
    (60_000_000,  0.0010, 30_000),
    (150_000_000, 0.0020, 180_000),
    (300_000_000, 0.0035, 630_000),
]

RATE_PROP_STD: List[Tuple[float, float, float]] = [        # 재산세 표준세율
    (0,           0.0010, 0),
    (60_000_000,  0.0015, 30_000),
    (150_000_000, 0.0025, 180_000),
    (300_000_000, 0.0040, 630_000),
]

RATE_JBS_NORMAL: List[Tuple[float, float, float]] = [       # 종부세 일반세율
    (0,             0.005, 0),
    (300_000_000,   0.007, 600_000),
    (600_000_000,   0.010, 2_400_000),
    (1_200_000_000, 0.013, 6_000_000),
    (2_500_000_000, 0.015, 11_000_000),
    (5_000_000_000, 0.020, 36_000_000),
    (9_400_000_000, 0.027, 101_800_000),
]

RATE_JBS_HEAVY: List[Tuple[float, float, float]] = [        # 종부세 중과세율 (3주택 이상, 과표 12억 초과)
    (0,             0.005, 0),
    (300_000_000,   0.007, 600_000),
    (600_000_000,   0.010, 2_400_000),
    (1_200_000_000, 0.020, 12_000_000),
    (2_500_000_000, 0.030, 37_000_000),
    (5_000_000_000, 0.040, 87_000_000),
    (9_400_000_000, 0.050, 181_000_000),
]

AGE_OPTIONS = {
    "60세 미만 (공제 없음)": 0.0,
    "60~64세 (20%)": 0.2,
    "65~69세 (30%)": 0.3,
    "70세 이상 (40%)": 0.4,
}
HOLD_OPTIONS = {
    "5년 미만 (공제 없음)": 0.0,
    "5~9년 (20%)": 0.2,
    "10~14년 (40%)": 0.4,
    "15년 이상 (50%)": 0.5,
}


def bracket_tax(base: float, table: List[Tuple[float, float, float]]) -> float:
    """누진세율표에서 세액 계산: 해당 구간 세율 x 과세표준 - 누진공제액"""
    lower, rate, deduct = table[0]
    for lo, r, d in table:
        if base >= lo:
            lower, rate, deduct = lo, r, d
        else:
            break
    return max(0.0, base * rate - deduct)


def won(v: float) -> str:
    return f"{v:,.0f}원"


# =========================================================
# 데이터 구조
# =========================================================

@dataclass
class PropertyRow:
    name: str
    gongsi_manwon: float   # 공시가격 (만원, "물건 전체" 기준)
    share_pct: float       # 내 지분 (0~100)


@dataclass
class PropertyTaxDetail:
    name: str
    gongsi_manwon: float
    share_pct: float
    fmv: float
    rate_type: str
    my_main: float
    my_city: float
    my_edu: float
    my_total: float


@dataclass
class CalcResult:
    details: List[PropertyTaxDetail] = field(default_factory=list)
    p_main_sum: float = 0.0
    p_total_sum: float = 0.0
    lump_july: bool = False
    july_calc: float = 0.0
    sep_calc: float = 0.0
    paid_july: Optional[float] = None
    ratio: float = 1.0
    diff: Optional[float] = None
    july_total: float = 0.0
    sep_total: float = 0.0
    is_one: bool = True
    heavy: bool = False
    deduct_amt: float = 0.0
    j_base: float = 0.0
    j_gross: float = 0.0
    p_credit: float = 0.0
    age_hold_credit: float = 0.0
    cred_rate: float = 0.0
    j_net: float = 0.0
    j_rural: float = 0.0
    j_total: float = 0.0


def calculate(properties: List[PropertyRow], is_one: bool, jongbuse_house_count: int,
              age_rate: float, hold_rate: float, paid_july: Optional[float]) -> CalcResult:
    heavy = jongbuse_house_count >= 3

    details: List[PropertyTaxDetail] = []
    p_main_sum = 0.0
    p_total_sum = 0.0
    gongsi_won_share_sum = 0.0

    for prop in properties:
        gongsi_won = max(0.0, prop.gongsi_manwon) * 10000
        share = max(0.0, min(100.0, prop.share_pct)) / 100

        if is_one:
            fmv = 0.43 if gongsi_won <= 3e8 else (0.44 if gongsi_won <= 6e8 else 0.45)
        else:
            fmv = 0.60

        use_special = is_one and gongsi_won <= 9e8
        rate_type = "1주택 특례세율" if use_special else "표준세율"
        table = RATE_PROP_SPECIAL if use_special else RATE_PROP_STD

        full_base = gongsi_won * fmv
        full_main = bracket_tax(full_base, table)

        my_main = full_main * share
        my_city = full_base * share * 0.0014
        my_edu = my_main * 0.2
        my_total = my_main + my_city + my_edu

        details.append(PropertyTaxDetail(
            name=prop.name, gongsi_manwon=prop.gongsi_manwon, share_pct=prop.share_pct,
            fmv=fmv, rate_type=rate_type,
            my_main=my_main, my_city=my_city, my_edu=my_edu, my_total=my_total,
        ))

        p_main_sum += my_main
        p_total_sum += my_total
        gongsi_won_share_sum += gongsi_won * share

    lump_july = p_main_sum <= 200_000
    july_calc = p_total_sum if lump_july else p_total_sum / 2
    sep_calc = 0.0 if lump_july else p_total_sum / 2

    if paid_july and paid_july > 0 and july_calc > 0:
        ratio = paid_july / july_calc
        diff = paid_july - july_calc
        sep_calc *= ratio
    else:
        ratio = 1.0
        diff = None

    deduct_amt = 1.2e9 if is_one else 9e8
    j_base = max(0.0, gongsi_won_share_sum - deduct_amt) * 0.6

    if j_base > 0:
        jbs_table = RATE_JBS_HEAVY if heavy else RATE_JBS_NORMAL
        j_gross = bracket_tax(j_base, jbs_table)
        p_credit = min(j_base * 0.6 * 0.004, p_main_sum * ratio)
    else:
        j_gross = 0.0
        p_credit = 0.0

    after_credit = max(0.0, j_gross - p_credit)
    eff_age = age_rate if is_one else 0.0
    eff_hold = hold_rate if is_one else 0.0
    cred_rate = min(0.8, eff_age + eff_hold)
    age_hold_credit = after_credit * cred_rate
    j_net = after_credit - age_hold_credit
    j_rural = j_net * 0.2
    j_total = j_net + j_rural

    july_total = paid_july if (paid_july and paid_july > 0) else july_calc
    sep_total = sep_calc

    return CalcResult(
        details=details, p_main_sum=p_main_sum, p_total_sum=p_total_sum,
        lump_july=lump_july, july_calc=july_calc, sep_calc=sep_calc,
        paid_july=paid_july, ratio=ratio, diff=diff,
        july_total=july_total, sep_total=sep_total,
        is_one=is_one, heavy=heavy, deduct_amt=deduct_amt,
        j_base=j_base, j_gross=j_gross, p_credit=p_credit,
        age_hold_credit=age_hold_credit, cred_rate=cred_rate,
        j_net=j_net, j_rural=j_rural, j_total=j_total,
    )


# =========================================================
# 연도별 기록 / 내년 예상
# =========================================================

def add_or_update_history(history: List[dict], year: int, res: CalcResult,
                          today_iso: str) -> List[dict]:
    """같은 연도 기록이 있으면 덮어쓰고, 없으면 추가 후 연도순 정렬"""
    record = {
        "year": int(year),
        "july": res.july_total,
        "sep": res.sep_total,
        "jongbuse": res.j_total,
        "total": res.july_total + res.sep_total + res.j_total,
        "saved_at": today_iso,
    }
    history = [h for h in history if int(h.get("year", 0)) != int(year)]
    history.append(record)
    history.sort(key=lambda h: h["year"])
    return history


def estimate_next_year(history: List[dict]) -> Optional[dict]:
    """최소 2개 연도 기록이 있으면 연평균 증가율로 내년 세금을 추정"""
    if len(history) < 2:
        return None
    first, last = history[0], history[-1]
    years_gap = last["year"] - first["year"]
    if years_gap <= 0:
        return None

    def growth(key: str) -> float:
        if first.get(key, 0) <= 0 or last.get(key, 0) <= 0:
            return 0.0
        return (last[key] / first[key]) ** (1 / years_gap) - 1

    g_july, g_sep, g_jbs = growth("july"), growth("sep"), growth("jongbuse")
    next_year = last["year"] + 1
    est_july = last["july"] * (1 + g_july)
    est_sep = last["sep"] * (1 + g_sep)
    est_jbs = last["jongbuse"] * (1 + g_jbs)
    return {
        "year": next_year,
        "july": est_july,
        "sep": est_sep,
        "jongbuse": est_jbs,
        "total": est_july + est_sep + est_jbs,
        "avg_growth": (g_july + g_sep + g_jbs) / 3,
    }
