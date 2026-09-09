"""
==========================================================================
호텔 가격 감시 엔진
==========================================================================
[이 모듈이 하는 것]
  · 감시 조건(호텔·날짜·인원·아이 만 나이)을 정리합니다
  · RapidAPI 로 그 조건의 **가장 싼 예약 가능 가격**을 조회합니다
  · 목표가 이하 / 기준가 대비 하락 조건을 판정합니다
  · 텔레그램으로 알림을 보냅니다
  · 조회한 가격을 이력으로 쌓아 추이를 볼 수 있게 합니다

[중요 - 이 파일은 streamlit 을 쓰지 않습니다]
  GitHub Actions 에서 화면 없이 돌리는 scripts/hotel_check.py 가 이 모듈을
  그대로 가져다 씁니다. streamlit 을 import 하면 Actions 에서 무거워지고,
  st.session_state 가 없어서 깨집니다. 그래서 숫자·날짜 변환도 app_kit 을
  쓰지 않고 이 안에서 따로 만들었습니다.

[가격 출처에 대한 솔직한 이야기]
  호텔 가격은 주식 시세처럼 공개 API 가 없습니다. 여기서 쓰는 것은
  RapidAPI 에 올라온 **비공식 래퍼**입니다. 그래서
    · 응답 구조가 예고 없이 바뀔 수 있습니다
    · 값이 실제 예약 화면과 몇 % 다를 수 있습니다 (세금·수수료 포함 여부)
  두 번째 문제 때문에 이 모듈은 "알림 = 예약 확정" 이 아니라
  "지금 확인해 볼 만하다" 는 신호로만 씁니다. 실제 값은 반드시
  예약 사이트에서 다시 보세요.

  첫 번째 문제 때문에 응답을 파싱할 때 **정해진 경로를 믿지 않습니다.**
  JSON 을 재귀로 훑어서 '이름 + 가격' 을 함께 가진 항목을 찾아냅니다.
  구조가 바뀌어도 이름과 가격이 있으면 계속 동작합니다.
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시.
모듈버전 = "2026-09-08"


import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------
# 기본값
# --------------------------------------------------------------------------
기본_호스트 = "booking-com15.p.rapidapi.com"
기본_통화 = "KRW"
최대_아이수 = 10          # 대부분의 예약 사이트가 이 정도까지만 받습니다
최대_밤수 = 30
조회_시간제한 = 25

# 감시 표의 열 정의. app_kit.표만들기 에 그대로 넘깁니다.
감시열 = {
    "사용": "bool",
    "이름": "text",
    "도시": "text",
    "dest_id": "text",
    # ★ dest_id 만으로는 조회가 안 됩니다. API 는 그 dest_id 가 도시인지
    #   호텔인지(search_type)도 함께 요구합니다. 특히 호텔 이름으로 직접
    #   검색해 찾은 dest_id 는 대개 "HOTEL" 타입인데, 이걸 안 넣고
    #   "CITY" 로 조회하면 그 dest_id 는 존재하지 않는 도시 취급을 받아
    #   빈 결과가 돌아옵니다. 화면에는 안 보이는 값이라 사용자가 직접
    #   고칠 일은 없고, 도시 검색에서 자동으로 채워집니다.
    "종류": "text",
    "호텔": "text",
    "체크인": "date",
    "체크아웃": "date",
    "어른": "number",
    "아이나이": "text",
    "방수": "number",
    "목표가": "number",
    "하락률": "number",
}

# 이력 한 줄의 모양
이력열 = {"이름": "text", "날짜": "date", "가격": "number", "호텔": "text"}


def 기본_감시표():
    """처음 열었을 때 보여주는 예시 한 줄. 어떻게 적는지 보여주는 목적입니다."""
    오늘 = date.today()
    들어가는날 = 오늘 + timedelta(days=60)
    return [{
        "사용": True,
        "이름": "예) 오사카 겨울여행",
        "도시": "Osaka",
        "dest_id": "",
        "호텔": "",
        "체크인": 들어가는날,
        "체크아웃": 들어가는날 + timedelta(days=2),
        "어른": 2,
        "아이나이": "5, 8",
        "방수": 1,
        "목표가": 0,
        "하락률": 10,
    }]


# ==========================================================================
# 값 읽기 (streamlit·app_kit 없이 동작해야 하므로 여기서 따로 만듭니다)
# ==========================================================================

def _수(값, 기본=0.0):
    if 값 is None:
        return 기본
    if isinstance(값, bool):
        return float(값)
    if isinstance(값, (int, float)):
        # NaN 은 자기 자신과 다릅니다. pandas 를 import 하지 않고 걸러냅니다.
        return 기본 if 값 != 값 else float(값)
    글자 = re.sub(r"[^\d.\-]", "", str(값))
    if 글자 in ("", "-", ".", "-."):
        return 기본
    try:
        return float(글자)
    except ValueError:
        return 기본


def _정수(값, 기본=0):
    return int(round(_수(값, 기본)))


def _날짜(값):
    """어떤 형태든 datetime.date 로. 못 읽으면 None."""
    if 값 is None:
        return None
    if isinstance(값, datetime):
        return 값.date()
    if isinstance(값, date):
        return 값
    글자 = str(값).strip()
    if not 글자 or 글자.lower() in ("nan", "nat", "none"):
        return None
    맞음 = re.match(r"^(\d{4})\D(\d{1,2})\D(\d{1,2})", 글자)
    if not 맞음:
        맞음 = re.match(r"^(\d{4})(\d{2})(\d{2})$", 글자)
    if not 맞음:
        return None
    try:
        return date(int(맞음.group(1)), int(맞음.group(2)), int(맞음.group(3)))
    except ValueError:
        return None


_나이숫자 = re.compile(r"\d+")


def 아이나이_읽기(값):
    """'5,8' · '만 5세 만 8세' · [5, 8] → [5, 8]

    ★ 여기 적는 나이는 그대로 **만 나이**입니다.
      예약 사이트가 요구하는 나이도 만 나이라서 변환이 필요 없습니다.
      단, 기준은 '오늘' 이 아니라 **체크인 당일**입니다. 여행이 생일 뒤라면
      한 살 올려 적어야 맞습니다. 만나이() 함수를 쓰면 계산해 줍니다.
    """
    if 값 is None:
        return []
    if isinstance(값, (list, tuple)):
        조각 = [str(x) for x in 값]
    else:
        if 값 != 값:                      # NaN
            return []
        조각 = _나이숫자.findall(str(값))
    나이들 = []
    for x in 조각:
        찾음 = _나이숫자.search(str(x))
        if not 찾음:
            continue
        n = int(찾음.group())
        if 0 <= n <= 17:                  # 만 18세부터는 어른으로 셉니다
            나이들.append(n)
    return sorted(나이들)[:최대_아이수]


def 아이나이_글자(나이들) -> str:
    나이들 = 아이나이_읽기(나이들)
    return ", ".join(str(n) for n in 나이들)


def 만나이(생일, 기준일=None) -> int:
    """체크인 당일의 만 나이. 아이 나이를 손으로 세다 틀리는 것을 막습니다."""
    생 = _날짜(생일)
    기준 = _날짜(기준일) or date.today()
    if 생 is None:
        return -1
    나이 = 기준.year - 생.year
    if (기준.month, 기준.day) < (생.month, 생.day):
        나이 -= 1
    return max(나이, 0)


def 밤수(체크인, 체크아웃) -> int:
    들 = _날짜(체크인)
    나 = _날짜(체크아웃)
    if not 들 or not 나:
        return 0
    return max((나 - 들).days, 0)


# ==========================================================================
# 감시 한 줄 정리
# ==========================================================================

def 행_정리(행) -> dict:
    """표에서 온 한 줄을 계산에 쓸 수 있는 모양으로 맞춥니다."""
    행 = dict(행 or {})
    아이 = 아이나이_읽기(행.get("아이나이"))
    들어감 = _날짜(행.get("체크인"))
    나옴 = _날짜(행.get("체크아웃"))
    정리 = {
        "사용": bool(행.get("사용", True)),
        "이름": str(행.get("이름") or "").strip(),
        "도시": str(행.get("도시") or "").strip(),
        "dest_id": str(행.get("dest_id") or "").strip(),
        # ★ 대소문자를 바꾸지 않고 그대로 둡니다. API 가 "hotel" 처럼
        #   소문자로 돌려준 값을 대문자로 바꿔 보내면, 대소문자를
        #   구분하는 API 에서는 dest_id 가 맞아도 거부당합니다.
        "종류": (str(행.get("종류") or "").strip() or "CITY"),
        "호텔": str(행.get("호텔") or "").strip(),
        "체크인": 들어감,
        "체크아웃": 나옴,
        "어른": max(_정수(행.get("어른"), 2), 1),
        "아이나이": 아이,
        "아이수": len(아이),
        "방수": max(_정수(행.get("방수"), 1), 1),
        "목표가": max(_수(행.get("목표가"), 0.0), 0.0),
        "하락률": min(max(_수(행.get("하락률"), 0.0), 0.0), 90.0),
        "밤수": 밤수(들어감, 나옴),
    }
    if not 정리["이름"]:
        # 이름이 이력·알림의 열쇠입니다. 비어 있으면 조건으로 만들어 둡니다.
        조각 = [정리["호텔"] or 정리["도시"] or "감시"]
        if 들어감:
            조각.append(들어감.isoformat())
        정리["이름"] = " ".join(조각)
    정리["인원글"] = 인원_설명(정리)
    return 정리


def 인원_설명(정리) -> str:
    조각 = [f"어른 {정리['어른']}명"]
    if 정리["아이나이"]:
        조각.append("아이 " + "·".join(f"만{n}세" for n in 정리["아이나이"]))
    if 정리["방수"] > 1:
        조각.append(f"{정리['방수']}실")
    return " / ".join(조각)


def 일정_설명(정리) -> str:
    들, 나 = 정리["체크인"], 정리["체크아웃"]
    if not 들 or not 나:
        return "날짜 미정"
    return f"{들.isoformat()} ~ {나.isoformat()} ({정리['밤수']}박)"


def 부족한것(정리) -> list:
    """조회하려면 더 채워야 하는 항목. 비어 있으면 조회 가능합니다."""
    빠짐 = []
    if not 정리.get("dest_id") and not 정리.get("도시"):
        빠짐.append("도시")
    if not 정리.get("dest_id"):
        빠짐.append("도시 확정(dest_id)")
    if not 정리.get("체크인"):
        빠짐.append("체크인")
    if not 정리.get("체크아웃"):
        빠짐.append("체크아웃")
    if 정리.get("체크인") and 정리.get("체크아웃"):
        if 정리["밤수"] <= 0:
            빠짐.append("체크아웃이 체크인보다 뒤여야 합니다")
        elif 정리["밤수"] > 최대_밤수:
            빠짐.append(f"{최대_밤수}박까지만 조회합니다")
        elif 정리["체크인"] < date.today():
            빠짐.append("체크인이 지난 날짜입니다")
    return 빠짐


# ==========================================================================
# RapidAPI 통신
# ==========================================================================

def _GET(경로, 매개, 키, 호스트, 시간제한=조회_시간제한):
    url = f"https://{호스트}{경로}"
    if 매개:
        url += "?" + urllib.parse.urlencode(매개)
    req = urllib.request.Request(url)
    req.add_header("x-rapidapi-key", 키)
    req.add_header("x-rapidapi-host", 호스트)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "personal-dashboard")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        원문 = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(원문)
    except json.JSONDecodeError:
        return {"_원문": 원문[:2000]}


def 오류설명(e) -> str:
    if isinstance(e, urllib.error.HTTPError):
        안내 = {
            400: "요청 값이 잘못됐습니다. 날짜·인원·아이 나이를 확인하세요.",
            401: "RapidAPI 키가 잘못되었습니다. rapidapi_key 를 다시 확인하세요.",
            403: "이 API 를 구독하지 않았습니다. RapidAPI 에서 해당 API 의 "
                 "Subscribe 를 누르세요(무료 플랜도 구독이 필요합니다).",
            404: "주소가 맞지 않습니다. rapidapi_host 가 맞는지 확인하세요.",
            429: "호출 한도를 넘었습니다. 이번 달 무료 할당량을 다 썼거나 "
                 "너무 자주 조회했습니다. 확인 주기를 늘리세요.",
        }.get(e.code, "")
        return f"응답 {e.code}. {안내}".strip()
    if isinstance(e, urllib.error.URLError):
        return f"연결하지 못했습니다 ({e.reason})."
    return f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# 응답 해석 — 정해진 경로를 믿지 않고 JSON 을 훑습니다
# --------------------------------------------------------------------------
_이름키 = ("hotel_name", "property_name", "name", "title", "displayName")
_가격키 = ("grossPrice", "grossAmount", "gross_amount", "allInclusivePrice",
        "all_inclusive_price", "strikethroughPrice", "price", "totalPrice",
        "total_price", "amount", "min_total_price")
_금액키 = ("value", "amount", "amountRounded", "amountUnformatted", "price")
_링크키 = ("url", "hotel_url", "deeplink", "link")


def _이름_찾기(d):
    for k in _이름키:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):                 # {"name": {"text": "..."}}
            for k2 in ("text", "value", "en"):
                v2 = v.get(k2)
                if isinstance(v2, str) and v2.strip():
                    return v2.strip()
    return ""


def _금액_읽기(값):
    if isinstance(값, bool):
        return None
    if isinstance(값, (int, float)):
        return float(값) if 값 == 값 and 값 > 0 else None
    if isinstance(값, str):
        수 = re.sub(r"[^\d.]", "", 값)
        try:
            f = float(수)
        except ValueError:
            return None
        return f if f > 0 else None
    if isinstance(값, dict):
        for k in _금액키:
            찾음 = _금액_읽기(값.get(k))
            if 찾음:
                return 찾음
    return None


def _통화_찾기(값):
    if isinstance(값, dict):
        for k in ("currency", "currencyCode", "currency_code", "curr_code"):
            v = 값.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().upper()
        for v in 값.values():
            찾음 = _통화_찾기(v)
            if 찾음:
                return 찾음
    return ""


def _가격_찾기(d):
    """(가격, 통화). 중첩 어디에 있어도 찾습니다. 없으면 (None, '')."""
    후보 = []
    def 재귀(o, 깊이=0):
        if 깊이 > 6 or not isinstance(o, (dict, list)):
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _가격키:
                    금액 = _금액_읽기(v)
                    if 금액:
                        후보.append((금액, _통화_찾기(v) or _통화_찾기(o)))
                재귀(v, 깊이 + 1)
        else:
            for v in o[:40]:
                재귀(v, 깊이 + 1)
    재귀(d)
    if not 후보:
        return None, ""
    # 여러 개면 가장 싼 것 — 정가(strikethrough)보다 실제 낼 값을 씁니다
    가격, 통화 = min(후보, key=lambda x: x[0])
    return 가격, 통화


def _링크_찾기(d):
    for k in _링크키:
        v = d.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def _항목_해석(d):
    if not isinstance(d, dict):
        return None
    이름 = _이름_찾기(d)
    if not 이름:
        prop = d.get("property")
        if isinstance(prop, dict):
            이름 = _이름_찾기(prop)
    가격, 통화 = _가격_찾기(d)
    if not 이름 or not 가격:
        return None
    return {"호텔": 이름, "가격": float(가격), "통화": (통화 or 기본_통화).upper(),
            "링크": _링크_찾기(d)}


def 호텔목록_해석(자료) -> list:
    """응답 JSON 에서 '이름 + 가격' 을 가진 항목들의 목록을 찾아냅니다."""
    후보목록 = []

    def 재귀(o, 깊이=0):
        if 깊이 > 8:
            return
        if isinstance(o, list):
            해석된 = [x for x in (_항목_해석(v) for v in o[:200]) if x]
            if 해석된:
                후보목록.append(해석된)
            for v in o[:200]:
                재귀(v, 깊이 + 1)
        elif isinstance(o, dict):
            for v in o.values():
                재귀(v, 깊이 + 1)

    재귀(자료)
    if not 후보목록:
        return []
    return max(후보목록, key=len)


def 이름_맞나(호텔이름, 찾는말) -> bool:
    """공백·대소문자 무시하고 포함 여부를 봅니다."""
    if not 찾는말:
        return True
    a = re.sub(r"\s+", "", str(호텔이름 or "")).lower()
    b = re.sub(r"\s+", "", str(찾는말)).lower()
    return bool(b) and b in a


# --------------------------------------------------------------------------
# 바깥에서 쓰는 조회 함수
# --------------------------------------------------------------------------

def 도시_찾기(질의, 키, 호스트=기본_호스트):
    """(목록, 오류). 목록 = [{"이름","라벨","dest_id","종류"}]

    감시 표에는 도시 이름 대신 **dest_id** 를 넣어야 조회가 됩니다.
    사람이 외울 수 없는 값이라 이 함수로 찾아서 넣어 줍니다.
    """
    if not 키:
        return [], "RapidAPI 키가 없습니다."
    if not str(질의 or "").strip():
        return [], "찾을 도시 이름을 넣으세요."
    try:
        결과 = _GET("/api/v1/hotels/searchDestination",
                  {"query": str(질의).strip()}, 키, 호스트)
    except Exception as e:                                   # noqa: BLE001
        return [], 오류설명(e)

    자료 = 결과.get("data") if isinstance(결과, dict) else None
    if not isinstance(자료, list):
        자료 = 결과 if isinstance(결과, list) else []
    나온것 = []
    for d in 자료:
        if not isinstance(d, dict):
            continue
        아이디 = d.get("dest_id") or d.get("destId") or d.get("id")
        if 아이디 in (None, ""):
            continue
        나온것.append({
            "이름": str(d.get("name") or d.get("city_name") or "").strip(),
            "라벨": str(d.get("label") or d.get("name") or "").strip(),
            "dest_id": str(아이디),
            # ★ 대문자로 바꾸면 안 됩니다. 실제 API 는 "hotel" 처럼
            #   소문자로 돌려주는데, 대소문자를 구분하는 API 라면 대문자로
            #   바꿔 보내는 순간 dest_id 가 맞아도 거부당합니다. API 가
            #   돌려준 값을 그대로 씁니다.
            "종류": str(d.get("search_type") or d.get("dest_type")
                     or "CITY").strip(),
            "나라": str(d.get("country") or "").strip(),
            "호텔수": _정수(d.get("nr_hotels") or d.get("hotels"), 0),
        })
    if not 나온것:
        return [], "찾은 결과가 없습니다. 영어 이름으로 넣어 보세요 (예: Osaka)."
    return 나온것, None


def 호텔_검색(행, 키, 호스트=기본_호스트, 통화=기본_통화):
    """(목록, 오류, 원본JSON)

    목록은 싼 것부터 정렬됩니다. 행에 '호텔' 이 적혀 있으면 그 이름이
    들어간 것만 남깁니다.
    """
    if not 키:
        return [], "RapidAPI 키가 없습니다.", None
    정리 = 행 if isinstance(행, dict) and "밤수" in 행 else 행_정리(행)
    빠짐 = 부족한것(정리)
    if 빠짐:
        return [], "먼저 채워야 합니다: " + ", ".join(빠짐), None

    매개 = {
        "dest_id": 정리["dest_id"],
        "search_type": 정리.get("종류") or "CITY",
        "arrival_date": 정리["체크인"].isoformat(),
        "departure_date": 정리["체크아웃"].isoformat(),
        "adults": 정리["어른"],
        "room_qty": 정리["방수"],
        "page_number": 1,
        "currency_code": (통화 or 기본_통화).upper(),
        "units": "metric",
        "temperature_unit": "c",
        "languagecode": "ko",
    }
    # ★ 아이 나이는 이 한 줄이 전부입니다. 빼먹으면 '어른만' 가격이 나옵니다.
    if 정리["아이나이"]:
        매개["children_age"] = ",".join(str(n) for n in 정리["아이나이"])

    try:
        원본 = _GET("/api/v1/hotels/searchHotels", 매개, 키, 호스트)
    except Exception as e:                                   # noqa: BLE001
        return [], 오류설명(e), None

    목록 = 호텔목록_해석(원본)
    if not 목록:
        쪽지 = ""
        if isinstance(원본, dict):
            쪽지 = str(원본.get("message") or 원본.get("_원문") or "")[:200]
        return [], ("가격을 찾지 못했습니다. 응답 구조가 바뀌었을 수 있습니다. "
                    "'응답 원본 보기' 를 열어 확인하세요. " + 쪽지).strip(), 원본

    if 정리["호텔"]:
        걸러낸 = [h for h in 목록 if 이름_맞나(h["호텔"], 정리["호텔"])]
        if not 걸러낸:
            return [], (f"'{정리['호텔']}' 이(가) 검색 결과에 없습니다. "
                        f"({len(목록)}곳 중 없음) 이름의 일부만 적거나 "
                        "호텔 칸을 비워 도시 최저가로 보세요."), 원본
        목록 = 걸러낸

    목록.sort(key=lambda h: h["가격"])
    return 목록, None, 원본


def 최저가(목록):
    """(가격, 호텔이름, 통화). 목록이 비면 (0, '', '')."""
    if not 목록:
        return 0.0, "", ""
    첫 = min(목록, key=lambda h: h["가격"])
    return 첫["가격"], 첫["호텔"], 첫["통화"]


# ==========================================================================
# 알림 판정
# ==========================================================================
#  ★ 여기서 가장 중요한 것은 "같은 가격으로 계속 울리지 않게" 하는 것입니다.
#    6시간마다 확인하는데 조건을 만족한 채로 며칠 있으면 알림이 열 번 넘게
#    옵니다. 그러면 알림을 끄게 되고, 정작 더 싸졌을 때를 놓칩니다.
#    그래서 '이미 알린 가격보다 더 싸졌을 때만' 다시 보냅니다.

def 조건_판정(정리, 현재가, 기준가=None, 마지막알림가=None) -> dict:
    결과 = {
        "알림": False, "이유들": [], "보류": "",
        "목표달성": False, "하락달성": False,
        "하락폭": 0.0, "기준가": _수(기준가, 0.0),
        "목표대비": 0.0,
    }
    현재 = _수(현재가, 0.0)
    if 현재 <= 0:
        결과["보류"] = "가격을 읽지 못했습니다."
        return 결과

    목표 = _수(정리.get("목표가"), 0.0)
    if 목표 > 0:
        결과["목표대비"] = 현재 - 목표
        if 현재 <= 목표:
            결과["목표달성"] = True
            결과["이유들"].append(
                f"목표가 {목표:,.0f}원 이하 (지금 {현재:,.0f}원)")

    기준 = 결과["기준가"]
    요구 = _수(정리.get("하락률"), 0.0)
    if 기준 > 0:
        결과["하락폭"] = (기준 - 현재) / 기준 * 100
        if 요구 > 0 and 결과["하락폭"] >= 요구:
            결과["하락달성"] = True
            결과["이유들"].append(
                f"처음 본 값 {기준:,.0f}원보다 {결과['하락폭']:.1f}% 내림 "
                f"(기준 {요구:.0f}%)")

    if not 결과["이유들"]:
        return 결과

    # 이미 알린 가격보다 싸지 않으면 다시 보내지 않습니다
    이전 = _수(마지막알림가, 0.0)
    if 이전 > 0 and 현재 >= 이전:
        결과["보류"] = (f"이미 {이전:,.0f}원에 알렸습니다. "
                     "더 싸지면 다시 보냅니다.")
        return 결과

    결과["알림"] = True
    return 결과


def 알림_문장(정리, 현재가, 판정, 요약=None) -> str:
    """텔레그램으로 보낼 글. HTML 모드로 보냅니다."""
    줄 = [f"🏨 <b>{_안전(정리['이름'])}</b>"]
    if 정리.get("호텔"):
        줄.append(f"　{_안전(정리['호텔'])}")
    줄.append(f"　{일정_설명(정리)}")
    줄.append(f"　{정리['인원글']}")
    줄.append("")
    줄.append(f"💰 <b>{_수(현재가, 0):,.0f}원</b>"
             + (f" ({정리['밤수']}박 총액)" if 정리["밤수"] else ""))
    if 정리["밤수"] > 0:
        줄.append(f"　1박당 약 {_수(현재가, 0) / 정리['밤수']:,.0f}원")
    for 이유 in 판정.get("이유들", []):
        줄.append(f"✅ {_안전(이유)}")
    if 요약 and 요약.get("최저") and 요약.get("횟수", 0) > 1:
        줄.append("")
        줄.append(f"📉 지금까지 최저 {요약['최저']:,.0f}원 "
                 f"/ 최고 {요약['최고']:,.0f}원 ({요약['횟수']}회 확인)")
        if _수(현재가, 0) <= 요약["최저"]:
            줄.append("🔥 <b>지금까지 본 중 가장 싼 값입니다</b>")
    줄.append("")
    줄.append("<i>실제 값은 예약 사이트에서 다시 확인하세요. "
             "세금·수수료 포함 여부가 다를 수 있습니다.</i>")
    return "\n".join(줄)


def _안전(글) -> str:
    """텔레그램 HTML 모드에서 깨지지 않게 막습니다."""
    return (str(글 or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def 알림_보내기(채널, 긴글, 짧은글=None) -> tuple:
    """(보낸수, 결과들, None)

    채널 = {"텔레그램": {"토큰": …, "방": …}}

    결과들 = [(채널이름, 성공여부, 메시지), …]

    ※ 세 번째 반환값은 항상 None 입니다. 여러 채널을 붙일 수 있게
      만들었던 자리로, 지금은 텔레그램 하나뿐이라 쓰이지 않지만
      호출하는 쪽(페이지·scripts/hotel_check.py)의 모양을 그대로
      두기 위해 남겨 뒀습니다.
    """
    채널 = 채널 or {}
    결과들 = []
    보낸수 = 0

    텔 = 채널.get("텔레그램") or {}
    if str(텔.get("토큰") or "").strip() and str(텔.get("방") or "").strip():
        좋음, 말 = 텔레그램_보내기(텔["토큰"], 텔["방"], 긴글)
        결과들.append(("텔레그램", 좋음, 말))
        보낸수 += 1 if 좋음 else 0

    return 보낸수, 결과들, None


def 쓸_수_있는_채널(채널) -> list:
    """설정이 갖춰진 채널 이름 목록."""
    채널 = 채널 or {}
    쓸것 = []
    텔 = 채널.get("텔레그램") or {}
    if str(텔.get("토큰") or "").strip() and str(텔.get("방") or "").strip():
        쓸것.append("텔레그램")
    return 쓸것


# ==========================================================================
# 가격 이력
# ==========================================================================

def 기록_추가(이력, 이름, 가격, 호텔="", 날짜=None, 하루한번=True) -> list:
    """이력에 한 줄 추가한 **새 목록**을 돌려줍니다 (원본은 그대로).

    하루한번=True 면 같은 날 같은 이름의 기록을 덮어씁니다. 6시간마다
    확인하면 하루에 4줄씩 쌓여서 몇 달이면 표가 못 볼 지경이 됩니다.
    추이를 보는 데는 하루 한 점이면 충분합니다.
    """
    # dict 가 아닌 줄이 섞여 있으면 아래에서 .get 이 터집니다. 저장 파일을
    # 손으로 고치거나 예전 형식이 남아 있으면 실제로 생깁니다.
    새것 = [dict(r) for r in (이력 or []) if isinstance(r, dict)]
    그날 = _날짜(날짜) or date.today()
    값 = _수(가격, 0.0)
    if 값 <= 0:
        return 새것
    한줄 = {"이름": str(이름 or ""), "날짜": 그날, "가격": 값,
          "호텔": str(호텔 or "")}
    if 하루한번:
        for i, r in enumerate(새것):
            if str(r.get("이름")) == 한줄["이름"] and _날짜(r.get("날짜")) == 그날:
                # 같은 날이면 더 싼 값을 남깁니다 (그날 잡을 수 있었던 값)
                if _수(r.get("가격"), 0.0) <= 값:
                    return 새것
                새것[i] = 한줄
                return 새것
    새것.append(한줄)
    새것.sort(key=lambda r: (str(r.get("이름")),
                           (_날짜(r.get("날짜")) or date.min)))
    return 새것


def 이력_요약(이력, 이름) -> dict:
    """{횟수, 최저, 최고, 최근, 최근날짜, 처음, 점들}"""
    점들 = []
    for r in (이력 or []):
        if not isinstance(r, dict):
            continue
        if str(r.get("이름")) != str(이름):
            continue
        그날 = _날짜(r.get("날짜"))
        값 = _수(r.get("가격"), 0.0)
        if 그날 and 값 > 0:
            점들.append((그날, 값))
    점들.sort(key=lambda x: x[0])
    if not 점들:
        return {"횟수": 0, "최저": 0.0, "최고": 0.0, "최근": 0.0,
                "최근날짜": None, "처음": 0.0, "점들": []}
    값들 = [v for _, v in 점들]
    return {
        "횟수": len(점들),
        "최저": min(값들),
        "최고": max(값들),
        "최근": 값들[-1],
        "최근날짜": 점들[-1][0],
        "처음": 값들[0],
        "점들": 점들,
    }


def 기억_읽기(상태, 이름) -> dict:
    """상태에서 그 감시의 기억을 꺼냅니다. 모양이 이상하면 빈 dict.

    저장 파일이 손으로 고쳐졌거나 예전 형식이면 상태 값이 dict 가 아닐 수
    있습니다. 그대로 .get 을 부르면 페이지가 통째로 죽습니다.
    """
    if not isinstance(상태, dict):
        return {}
    값 = 상태.get(str(이름))
    return dict(값) if isinstance(값, dict) else {}


def 기준가_정하기(정리, 이력, 저장된=None):
    """'현재보다 하락' 의 기준이 되는 값.

    저장된 기준가가 있으면 그것을 씁니다. 없으면 이력의 첫 값입니다.
    ★ 이력의 '최근값' 을 기준으로 삼으면 안 됩니다. 값이 조금씩 오르면
      기준도 같이 올라가서, 크게 비싸진 뒤 살짝 내린 것을 '하락' 으로
      착각합니다. 기준은 처음 본 값에 고정합니다.
    """
    저장 = _수(저장된, 0.0)
    if 저장 > 0:
        return 저장
    요약 = 이력_요약(이력, 정리["이름"])
    return 요약["처음"]


# ==========================================================================
# 텔레그램
# ==========================================================================

def 텔레그램_보내기(토큰, 채팅id, 글, 시간제한=15):
    """(성공, 메시지)

    토큰이 주소에 들어가는 것은 텔레그램 Bot API 의 방식입니다. HTTPS 라
    전송 중에는 보이지 않지만, 토큰은 secrets 에만 두고 코드나 저장소에는
    절대 넣지 마세요.
    """
    if not 토큰 or not 채팅id:
        return False, "텔레그램 토큰 또는 chat_id 가 없습니다."
    주소 = f"https://api.telegram.org/bot{str(토큰).strip()}/sendMessage"
    본문 = urllib.parse.urlencode({
        "chat_id": str(채팅id).strip(),
        "text": str(글),
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(주소, data=본문, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=시간제한) as resp:
            결과 = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        속 = ""
        try:
            속 = json.loads(e.read().decode("utf-8", "replace")).get(
                "description", "")
        except Exception:                                    # noqa: BLE001
            pass
        안내 = {
            401: "봇 토큰이 잘못되었습니다.",
            400: "chat_id 가 잘못되었거나, 봇에게 먼저 말을 걸지 않았습니다. "
                 "텔레그램에서 봇을 찾아 /start 를 눌러 주세요.",
            403: "봇이 차단되었습니다. 대화방에서 봇을 다시 허용하세요.",
        }.get(e.code, "")
        return False, f"텔레그램 응답 {e.code}. {안내} {속}".strip()
    except Exception as e:                                   # noqa: BLE001
        return False, f"보내지 못했습니다: {type(e).__name__}: {e}"
    if not 결과.get("ok"):
        return False, str(결과.get("description") or "알 수 없는 오류")
    return True, "보냈습니다."


def 텔레그램_채팅찾기(토큰, 시간제한=15):
    """봇에게 말을 건 대화방 id 를 찾아 줍니다. (목록, 오류)

    chat_id 를 손으로 알아내는 게 처음 설정에서 가장 막히는 부분입니다.
    봇에게 아무 말이나 보낸 뒤 이 함수를 부르면 id 가 나옵니다.
    """
    if not 토큰:
        return [], "봇 토큰이 없습니다."
    주소 = f"https://api.telegram.org/bot{str(토큰).strip()}/getUpdates"
    try:
        with urllib.request.urlopen(주소, timeout=시간제한) as resp:
            결과 = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                   # noqa: BLE001
        return [], f"읽지 못했습니다: {type(e).__name__}: {e}"
    if not 결과.get("ok"):
        return [], str(결과.get("description") or "알 수 없는 오류")

    본것, 목록 = set(), []
    for u in (결과.get("result") or []):
        방 = ((u.get("message") or u.get("edited_message")
              or u.get("channel_post") or {}).get("chat") or {})
        아이디 = 방.get("id")
        if 아이디 is None or 아이디 in 본것:
            continue
        본것.add(아이디)
        이름 = (방.get("title") or " ".join(
            x for x in (방.get("first_name"), 방.get("last_name")) if x)
            or 방.get("username") or "")
        목록.append({"chat_id": str(아이디), "이름": 이름,
                    "종류": str(방.get("type") or "")})
    if not 목록:
        return [], ("최근 대화가 없습니다. 텔레그램에서 봇을 찾아 "
                    "아무 말이나 보낸 뒤 다시 누르세요. "
                    "(24시간이 지난 대화는 안 보입니다)")
    return 목록, None


# ==========================================================================
# 한 줄 확인 — 페이지와 Actions 스크립트가 함께 씁니다
# ==========================================================================

def 한줄_확인(행, 상태, 이력, 키, 호스트=기본_호스트, 통화=기본_통화) -> dict:
    """감시 한 줄을 조회하고 판정까지 합니다. 알림은 보내지 않습니다.

    상태 = {이름: {"기준가": …, "마지막알림가": …}}  (앞선 확인의 기억)

    돌려주는 것
      {정리, 목록, 최저가, 호텔, 통화, 오류, 판정, 요약, 새이력, 새상태}
    """
    정리 = 행_정리(행)
    답 = {"정리": 정리, "목록": [], "최저가": 0.0, "호텔": "", "통화": "",
        "오류": None, "판정": None, "요약": None,
        "새이력": [dict(r) for r in (이력 or []) if isinstance(r, dict)],
        "새상태": 기억_읽기(상태, 정리["이름"]),
        "원본": None}

    목록, 오류, 원본 = 호텔_검색(정리, 키, 호스트, 통화)
    답["원본"] = 원본
    if 오류:
        답["오류"] = 오류
        return 답

    값, 호텔, 화폐 = 최저가(목록)
    답.update({"목록": 목록, "최저가": 값, "호텔": 호텔, "통화": 화폐})

    답["새이력"] = 기록_추가(답["새이력"], 정리["이름"], 값, 호텔)
    답["요약"] = 이력_요약(답["새이력"], 정리["이름"])

    기준 = 기준가_정하기(정리, 답["새이력"], 답["새상태"].get("기준가"))
    답["판정"] = 조건_판정(정리, 값, 기준, 답["새상태"].get("마지막알림가"))

    답["새상태"]["기준가"] = 기준 or 값
    답["새상태"]["최근가"] = 값
    답["새상태"]["최근확인"] = date.today().isoformat()
    if 답["판정"]["알림"]:
        답["새상태"]["마지막알림가"] = 값
        답["새상태"]["마지막알림일"] = date.today().isoformat()
    return 답
