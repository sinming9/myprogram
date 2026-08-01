"""
==========================================================================
연봉·급여 관리 계산 엔진
==========================================================================
salary_manager.py (tkinter 버전)의 계산 로직만 옮긴 것입니다.
tkinter Canvas 로 직접 그렸던 그래프는 Streamlit(plotly)에서 다시 그립니다.

데이터 구조 (기존 salary_data.json 과 호환):
{
  "2025": {
     "contract_annual": 60000000,
     "annual_gross": 0,
     "inflation": "2.1",
     "note": "승진",
     "months": [ {"month":1,"gross":..., "bonus":..., "bonus_separate":true,
                  "tax":..., "note":""}, ... ]
  }, ...
}
==========================================================================
"""

import ast
import re

YEARS = list(range(2010, 2036))
MONTHS = list(range(1, 13))

KOREA_CPI = {2010: 2.9, 2011: 4.0, 2012: 2.2, 2013: 1.3, 2014: 1.3, 2015: 0.7,
             2016: 1.0, 2017: 1.9, 2018: 1.5, 2019: 0.4, 2020: 0.5, 2021: 2.5,
             2022: 5.1, 2023: 3.6, 2024: 2.3, 2025: 2.1, 2026: 2.6}

평가_설명 = {
    "매우 양호": "물가를 충분히 웃도는 인상으로 실질 구매력이 좋아졌습니다.",
    "물가 방어": "물가상승률 이상으로 올라 실질 구매력을 지켰습니다.",
    "아쉬움": "인상은 되었지만 물가를 따라가지 못해 실질적으로는 소폭 감소했습니다.",
    "실질 하락": "물가를 반영하면 실질 구매력이 감소했습니다.",
    "감액": "전년보다 세전 연봉이 줄었습니다.",
    "첫 기록": "직전 연도 연봉을 입력하면 인상률을 평가할 수 있습니다.",
    "물가 입력 필요": "물가상승률을 입력하면 실질 인상률을 평가할 수 있습니다.",
    "자료 없음": "연봉을 입력하면 평가할 수 있습니다.",
}

평가_색상 = {
    "매우 양호": "#087A4C", "물가 방어": "#2168B3", "아쉬움": "#AD6A00",
    "실질 하락": "#C13C3C", "감액": "#A61E4D",
}


def as_number(value):
    """금액 또는 안전한 사칙연산식을 원 단위 정수로 바꿉니다.

    '1,000,000' / '100만' / '0.01억' / '125000 + 80000' 모두 허용.
    """
    try:
        text = str(value).replace(",", "").replace(" ", "").replace("원", "").strip()
        if not text or text.lower() in ("none", "nan", "-"):
            return 0
        multipliers = {"만": 10_000, "억": 100_000_000}
        text = re.sub(r"(\d+(?:\.\d+)?)(만|억)",
                      lambda m: str(float(m.group(1)) * multipliers[m.group(2)]), text)
        expression = ast.parse(text, mode="eval").body

        def calc(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return calc(node.operand) if isinstance(node.op, ast.UAdd) else -calc(node.operand)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                left, right = calc(node.left), calc(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left / right
            raise ValueError

        result = calc(expression)
        if result < 0:
            raise ValueError
        return int(round(result))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        raise ValueError("금액 형식이 올바르지 않습니다.")


def money(value):
    return f"{int(value):,}원"


# ----------------------------------------------------------------------
# 월별 행 계산
# ----------------------------------------------------------------------

def month_gross(row):
    if "gross" in row:
        return int(row.get("gross") or 0)
    return (int(row.get("base", 0) or 0) + int(row.get("allowance", 0) or 0)
            + int(row.get("bonus", 0) or 0))


def month_tax(row):
    if "tax" in row:
        return int(row.get("tax") or 0)
    return max(0, month_gross(row) - int(row.get("net", 0) or 0))


def month_total_gross(row):
    gross = month_gross(row)
    return gross + int(row.get("bonus", 0) or 0) if row.get("bonus_separate") else gross


# ----------------------------------------------------------------------
# 연도 단위 집계
# ----------------------------------------------------------------------

def 빈_연도자료():
    return {"contract_annual": 0, "annual_gross": 0, "inflation": "", "note": "", "months": []}


def get_year_data(data, year):
    return data.get(str(year), 빈_연도자료())


def totals(data, year):
    """(실제세전, 세후수령액, 상여금, 계약연봉) 반환"""
    record = get_year_data(data, year)
    months = record.get("months", [])
    gross_from_months = sum(month_total_gross(r) for r in months)
    annual_gross = gross_from_months or int(record.get("annual_gross", 0) or 0)
    contract_annual = int(record.get("contract_annual", 0) or 0)
    net = sum(max(0, month_total_gross(r) - month_tax(r)) for r in months)
    bonus = sum(int(r.get("bonus", 0) or 0) for r in months)
    return annual_gross, net, bonus, contract_annual


def base_salary_for_calc(data, year):
    """비교 기준 연봉: 계약 연봉이 있으면 계약 연봉, 없으면 실제 세전"""
    gross, _, _, contract = totals(data, year)
    return contract if contract else gross


def assess_raise(raise_rate, real_rate, gross, previous, inflation):
    if not gross:
        return "자료 없음"
    if not previous:
        return "첫 기록"
    if not inflation:
        return "물가 입력 필요"
    if raise_rate < 0:
        return "감액"
    if real_rate >= 2:
        return "매우 양호"
    if real_rate >= 0:
        return "물가 방어"
    if real_rate > -2:
        return "아쉬움"
    return "실질 하락"


def recommended_salary(records):
    """내년 권장 계약연봉. (금액, 적용률%) 반환"""
    if not records:
        return None, None
    raises = [r["raise"] for r in records[-3:] if r["raise"] is not None]
    inflations = [r["inflation"] for r in records[-3:] if r["inflation"] is not None]
    trend = sum(raises) / len(raises) if raises else 0
    inflation_goal = sum(inflations) / len(inflations) + 2 if inflations else 2
    target_rate = max(trend, inflation_goal)
    target = int(round(records[-1]["base_sal"] * (1 + target_rate / 100) / 10000) * 10000)
    return target, target_rate


def recommendation_basis(records):
    """권장 연봉 산출 근거 문구"""
    raises = [r["raise"] for r in records[-3:] if r["raise"] is not None]
    inflations = [r["inflation"] for r in records[-3:] if r["inflation"] is not None]
    trend = sum(raises) / len(raises) if raises else 0
    inflation_goal = (sum(inflations) / len(inflations) + 2) if inflations else 2
    basis = "최근 3년 평균 인상률" if trend >= inflation_goal else "최근 3년 평균 물가상승률 + 2%"
    return trend, inflation_goal, basis


def dashboard_records(data):
    """연봉 입력이 있는 연도만 모아서 연도순 리스트로 반환"""
    records = []
    for year in YEARS:
        gross, net, bonus, contract = totals(data, year)
        base_sal = base_salary_for_calc(data, year)
        if not base_sal:
            continue
        inflation = get_year_data(data, year).get("inflation", "")
        prev_base = base_salary_for_calc(data, year - 1) if year > YEARS[0] else 0
        raise_rate = ((base_sal / prev_base) - 1) * 100 if prev_base else None
        records.append({
            "year": year, "base_sal": base_sal, "gross": gross, "net": net,
            "bonus": bonus, "contract": contract,
            "inflation": float(inflation) if inflation else None,
            "raise": raise_rate,
        })
    return records


def inflation_adjusted_total(data, records):
    """과거 세전 총액을 최신 연도 물가 기준으로 환산한 누적액"""
    if not records:
        return 0
    latest_year = records[-1]["year"]
    total = 0.0
    for item in records:
        factor = 1.0
        for year in range(item["year"] + 1, latest_year + 1):
            entered = get_year_data(data, year).get("inflation", "")
            rate = float(entered) if entered else KOREA_CPI.get(year, 0)
            factor *= 1 + rate / 100
        total += item["gross"] * factor
    return int(round(total / 10000) * 10000)


def 연도별_표(data):
    """연도별 현황 표에 쓸 행 리스트를 만듭니다."""
    rows = []
    history = []
    for year in YEARS:
        record = get_year_data(data, year)
        gross, net, bonus, contract = totals(data, year)
        base_sal = base_salary_for_calc(data, year)
        inflation = record.get("inflation", "")

        prev_base = base_salary_for_calc(data, year - 1) if year > YEARS[0] else 0
        raise_rate = ((base_sal / prev_base) - 1) * 100 if base_sal and prev_base else None
        real_rate = (((1 + raise_rate / 100) / (1 + float(inflation) / 100) - 1) * 100
                     if raise_rate is not None and inflation else None)
        assessment = assess_raise(raise_rate, real_rate, base_sal, prev_base, inflation)
        expected, _ = recommended_salary(history)

        if base_sal:
            rows.append({
                "연도": year,
                "계약 연봉": contract,
                "실제 세전": gross,
                "예상 연봉": expected or 0,
                "세후 수령액": net,
                "상여금": bonus,
                "물가상승률(%)": float(inflation) if inflation else None,
                "명목 인상률(%)": raise_rate,
                "물가 반영 변화(%)": real_rate,
                "평가": assessment,
                "메모": record.get("note", ""),
            })
            history.append({
                "year": year, "base_sal": base_sal, "gross": gross, "contract": contract,
                "net": net, "bonus": bonus,
                "inflation": float(inflation) if inflation else None, "raise": raise_rate,
            })
    return rows


def 연도_평가(data, year):
    """선택 연도의 (평가, 설명, 명목인상률, 실질인상률) 반환"""
    record = get_year_data(data, year)
    base_sal = base_salary_for_calc(data, year)
    prev_base = base_salary_for_calc(data, year - 1) if year > YEARS[0] else 0
    inflation = record.get("inflation", "")
    raise_rate = ((base_sal / prev_base) - 1) * 100 if base_sal and prev_base else None
    real_rate = (((1 + raise_rate / 100) / (1 + float(inflation) / 100) - 1) * 100
                 if raise_rate is not None and inflation else None)
    assessment = assess_raise(raise_rate, real_rate, base_sal, prev_base, inflation)
    return assessment, 평가_설명.get(assessment, ""), raise_rate, real_rate


def 월_표시_급여(row):
    """입력 화면에 보여줄 '월 급여(상여 제외)' 금액"""
    gross = month_gross(row)
    if not row.get("bonus_separate"):
        gross = max(0, gross - int(row.get("bonus", 0) or 0))
    return gross
