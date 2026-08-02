"""
==========================================================================
importer - 예전에 저장해 둔 자료 파일을 알아서 알아보고 가져오는 모듈
==========================================================================
tkinter 버전 프로그램들이 만들던 파일과, 이 대시보드가 만드는 백업 파일을
모두 받아서 형식을 판별하고 변환합니다.

지원하는 파일
  · salary_data.json              연봉/급여 (tkinter 버전 = 현재 형식과 동일)
  · property_tax_settings.json    재산세 입력값 (tkinter 버전)
  · property_tax_history.json     재산세 연도별 기록 (tkinter 버전, 리스트 형태)
  · property_tax.json             재산세 (이 대시보드 백업)
  · 대출계산기_설정.json            대출 계산기 설정 (구/신 버전 모두)
  · 적금계산기.json 등             myapps 프로그램이 저장한 파일
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-08-02h"


import json
import re

# 종류 코드 -> (사람이 읽는 이름, 저장 키)
종류_설명 = {
    "salary": ("연봉·급여 자료", "salary"),
    "property_tax_settings": ("재산세 입력값 (tkinter 버전)", "property_tax"),
    "property_tax_history": ("재산세 연도별 기록 (tkinter 버전)", "property_tax"),
    "property_tax": ("재산세 자료 (대시보드 백업)", "property_tax"),
    "loan": ("대출 계산기 설정", "loan"),
    "unknown": ("알 수 없는 형식", None),
}


def _숫자(값, 기본=0.0):
    if 값 is None:
        return 기본
    if isinstance(값, (int, float)):
        숫자 = float(값)
        # 옛 파일에 NaN 이 그대로 들어있는 경우가 있어 기본값으로 처리
        return 기본 if 숫자 != 숫자 else 숫자
    글자 = str(값).replace(",", "").replace(" ", "").replace("원", "").strip()
    if not 글자:
        return 기본
    try:
        return float(글자)
    except ValueError:
        return 기본


def 연도키_모음(데이터: dict):
    return sorted(k for k in 데이터
                  if re.fullmatch(r"\d{4}", str(k)) and 1900 < int(k) < 2200)


def 판별(데이터):
    """파일 내용을 보고 종류 코드를 돌려줍니다."""
    if isinstance(데이터, list):
        if 데이터 and all(isinstance(x, dict) and "year" in x for x in 데이터):
            return "property_tax_history"
        return "unknown"

    if not isinstance(데이터, dict):
        return "unknown"

    if "원금" in 데이터 and ("상환개월수" in 데이터 or "첫납입일" in 데이터):
        return "loan"
    if "부동산" in 데이터 or ("history" in 데이터 and "is_one" in 데이터):
        return "property_tax"
    if "properties" in 데이터 or "jongbuse_count" in 데이터:
        return "property_tax_settings"

    연도들 = 연도키_모음(데이터)
    if 연도들:
        표본 = 데이터[연도들[0]]
        if isinstance(표본, dict) and (
                "months" in 표본 or "contract_annual" in 표본 or "annual_gross" in 표본):
            return "salary"
    return "unknown"


def 요약(종류, 데이터):
    """가져오기 전에 화면에 보여줄 한 줄 설명"""
    if 종류 == "salary":
        연도들 = 연도키_모음(데이터)
        채워진 = [y for y in 연도들
                if _숫자(데이터[y].get("contract_annual")) > 0
                or _숫자(데이터[y].get("annual_gross")) > 0
                or 데이터[y].get("months")]
        return (f"{len(연도들)}개 연도 ({연도들[0]}~{연도들[-1]}) · "
                f"자료가 있는 연도 {len(채워진)}개" if 연도들 else "연도 자료 없음")
    if 종류 == "property_tax_settings":
        수 = len(데이터.get("properties", []))
        return f"부동산 {수}건 · 1세대1주택={bool(데이터.get('is_one', True))}"
    if 종류 == "property_tax_history":
        연도들 = sorted(int(x["year"]) for x in 데이터 if str(x.get("year", "")).isdigit())
        return (f"연도별 기록 {len(데이터)}건 ({연도들[0]}~{연도들[-1]})"
                if 연도들 else f"연도별 기록 {len(데이터)}건")
    if 종류 == "property_tax":
        return (f"부동산 {len(데이터.get('부동산', []))}건 · "
                f"연도별 기록 {len(데이터.get('history', []))}건")
    if 종류 == "loan":
        return (f"원금 {_숫자(데이터.get('원금')):,.0f}원 · "
                f"{데이터.get('상환개월수', '?')}개월 · "
                f"중도상환 {len(데이터.get('중도상환목록', []))}건")
    return "내용을 알아볼 수 없습니다"


# ==========================================================================
# 변환
# ==========================================================================

def 재산세_설정_변환(옛자료: dict) -> dict:
    """tkinter property_tax_settings.json → 대시보드 형식"""
    부동산 = []
    for p in 옛자료.get("properties", []):
        공시 = _숫자(p.get("gongsi"))
        if 공시 <= 0:
            continue
        고지 = _숫자(p.get("actual"))
        부동산.append({
            "이름": str(p.get("name") or "부동산"),
            "공시가격(만원)": 공시,
            "지분(%)": _숫자(p.get("share"), 100.0) or 100.0,
            "실제 7월 고지액(선택)": 고지 if 고지 > 0 else None,
        })

    개수 = int(_숫자(옛자료.get("jongbuse_count"), len(부동산) or 1)) or 1
    결과 = {
        "부동산": 부동산,
        "is_one": bool(옛자료.get("is_one", True)),
        "house_count": max(1, 개수),
        "history": [],
    }
    if 옛자료.get("age"):
        결과["age_key"] = str(옛자료["age"])
    if 옛자료.get("hold"):
        결과["hold_key"] = str(옛자료["hold"])
    return 결과


def 재산세_기록_변환(옛목록: list) -> list:
    출력 = []
    for x in 옛목록:
        try:
            연도 = int(x["year"])
        except (KeyError, TypeError, ValueError):
            continue
        출력.append({
            "year": 연도,
            "july": _숫자(x.get("july")),
            "sep": _숫자(x.get("sep")),
            "jongbuse": _숫자(x.get("jongbuse")),
            "total": _숫자(x.get("total")) or (
                _숫자(x.get("july")) + _숫자(x.get("sep")) + _숫자(x.get("jongbuse"))),
            "saved_at": str(x.get("saved_at", "")),
        })
    출력.sort(key=lambda h: h["year"])
    return 출력


def 대출_설정_변환(옛자료: dict) -> dict:
    """구 버전 키 이름을 현재 형식으로 맞춤"""
    결과 = dict(옛자료)
    중도 = []
    for r in (옛자료.get("중도상환목록") or []):
        항목 = dict(r)
        if "이자(직접입력, 선택)" in 항목:
            항목["이자(직접입력)"] = 항목.pop("이자(직접입력, 선택)")
        항목.setdefault("이자(직접입력)", None)
        항목.setdefault("수수료(직접입력)", None)
        중도.append(항목)
    결과["중도상환목록"] = 중도
    # NaN 이 들어있던 금리 항목 정리
    금리 = []
    for r in (옛자료.get("금리스케줄") or []):
        try:
            시작 = int(r.get("시작회차"))
            금리값 = float(r.get("금리(%)"))
        except (TypeError, ValueError):
            continue
        금리.append({"시작회차": 시작, "금리(%)": 금리값})
    결과["금리스케줄"] = 금리
    결과.setdefault("이자정산방식", "원금분만")
    결과.setdefault("수수료율", 1.2)
    결과.setdefault("면제기간_개월", 36)
    return 결과


def 연봉_합치기(기존: dict, 새자료: dict, 덮어쓰기=True) -> tuple:
    """연도 단위로 합칩니다. (합쳐진자료, 추가된연도, 덮어쓴연도)"""
    결과 = dict(기존 or {})
    추가, 덮어씀 = [], []
    for 연도 in 연도키_모음(새자료):
        if 연도 in 결과:
            if not 덮어쓰기:
                continue
            덮어씀.append(연도)
        else:
            추가.append(연도)
        결과[연도] = 새자료[연도]
    return 결과, sorted(추가), sorted(덮어씀)


def 파일_읽기(올린파일):
    """(데이터, 종류, 오류메시지) 반환"""
    try:
        내용 = 올린파일.read()
        if isinstance(내용, bytes):
            내용 = 내용.decode("utf-8-sig", errors="replace")
        # tkinter 버전이 NaN 을 그대로 쓴 파일도 있어서 허용
        데이터 = json.loads(내용)
    except json.JSONDecodeError as e:
        return None, "unknown", f"JSON 형식이 아닙니다: {e}"
    except Exception as e:  # noqa: BLE001
        return None, "unknown", f"파일을 읽을 수 없습니다: {e}"
    return 데이터, 판별(데이터), None
