"""
==========================================================================
호텔 가격 알림
==========================================================================
[이 페이지가 하는 것]
  날짜·인원·아이 만 나이까지 정해서 호텔 가격을 지켜보고, 목표가 이하로
  내려가거나 처음 본 값보다 정해진 % 만큼 싸지면 텔레그램으로 알립니다.

[알아 두실 것 - 두 가지]

  1) 가격은 **비공식 API** 에서 옵니다
     호텔 가격은 주식 시세처럼 공개 API 가 없습니다. RapidAPI 에 올라온
     래퍼를 쓰기 때문에 실제 예약 화면과 몇 % 다를 수 있습니다
     (세금·수수료 포함 여부). 그래서 알림은 "지금 확인해 볼 만하다" 는
     신호이고, 실제 값은 예약 사이트에서 다시 봐야 합니다.

  2) 이 페이지를 열어 둬야 알림이 오는 게 **아닙니다**
     Streamlit 은 아무도 안 보면 잠듭니다. 잠든 앱은 아무것도 못 합니다.
     그래서 자동 확인은 GitHub Actions 가 6시간마다 대신 돌립니다.
     (아래 '자동으로 지켜보기' 참고) 이 페이지는 조건을 정하고, 지금 당장
     한 번 확인하고, 쌓인 가격 추이를 보는 곳입니다.
==========================================================================
"""

import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import storage  # noqa: E402
import ui  # noqa: E402
from app_kit import (고른위치, 날짜로, 불러온것_적용, 숫자로,
                     저장_불러오기, 표만들기)  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402
from engines import agoda as AG  # noqa: E402
from engines import hotel as HT  # noqa: E402

require_login(page_title="호텔 가격 알림", page_icon="🏨", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("🏨 호텔 가격 알림")
st.caption("날짜·인원·아이 만 나이까지 정해 두면, 싸질 때 **텔레그램으로 알려줍니다**")

# 이 페이지가 필요한 기능이 엔진에 실제로 있는지 먼저 봅니다.
# 화면 파일만 올리고 engines/hotel.py 를 안 올리면 여기서 걸립니다.
if not hasattr(HT, "한줄_확인"):
    st.error("**engines/hotel.py 가 없거나 예전 버전입니다.**", icon="🔄")
    st.markdown(
        "이 화면은 `engines/hotel.py` 가 함께 있어야 동작합니다.\n\n"
        "- 클라우드라면 저장소에 `engines/hotel.py` 를 올리세요\n"
        "- 내 PC 라면 서버를 끄고 다시 켜세요 (공용 파일은 켤 때만 읽습니다)")
    st.stop()

저장키 = "hotel"
기본설정 = {
    "감시": [],
    "이력": [],
    "상태": {},          # {감시이름: {기준가, 마지막알림가, 최근가, 최근확인}}
    "호스트": HT.기본_호스트,
    "통화": HT.기본_통화,
    "주기": 6,
    "알림켬": True,
}
통화목록 = ["KRW", "USD", "JPY", "EUR"]
주기목록 = [3, 6, 12, 24]


def _설정_정리(불러온: dict) -> dict:
    설정 = {}
    for k, v in 기본설정.items():
        설정[k] = list(v) if isinstance(v, list) else (
            dict(v) if isinstance(v, dict) else v)
    for k, v in (불러온 or {}).items():
        if k in 기본설정:
            설정[k] = v
    # 저장된 값이 엉뚱한 형이어도 아래 코드가 안 죽게 맞춰 둡니다
    if not isinstance(설정.get("감시"), list):
        설정["감시"] = []
    if not isinstance(설정.get("이력"), list):
        설정["이력"] = []
    # 줄 하나가 dict 가 아니면 이력을 읽는 곳마다 .get 이 터집니다
    설정["이력"] = [r for r in 설정["이력"] if isinstance(r, dict)]
    if not isinstance(설정.get("상태"), dict):
        설정["상태"] = {}
    설정["상태"] = {str(k): v for k, v in 설정["상태"].items()
                 if isinstance(v, dict)}
    if not 설정["감시"]:
        설정["감시"] = HT.기본_감시표()
    return 설정


if "호텔_설정" not in st.session_state:
    st.session_state["호텔_설정"] = _설정_정리(storage.불러오기(저장키, {}) or {})
st.session_state.setdefault("호텔_표버전", 0)
st.session_state.setdefault("호텔_결과", {})
st.session_state.setdefault("호텔_도시결과", [])
st.session_state.setdefault("호텔_아고다결과", [])


def _표원본_바꾸기(행들):
    # ★ data_editor 는 [원본 + 편집내역] 으로 결과를 만듭니다. 편집 결과를
    #   다시 원본에 넣으면 편집내역이 두 번 적용되어 방금 넣은 줄이
    #   사라집니다. 원본은 이 함수에서만 바꾸고, 바꿀 때는 표를 새로
    #   만듭니다(버전 올림).
    st.session_state["호텔_표원본"] = [dict(r) for r in (행들 or [])]
    st.session_state["호텔_표버전"] += 1


def _설정_적용(데이터):
    새것 = _설정_정리(데이터 or {})
    st.session_state["호텔_설정"] = 새것
    st.session_state["호텔_결과"] = {}
    _표원본_바꾸기(새것.get("감시"))


불러온것_적용("_호텔_적용대기", _설정_적용)
설정 = st.session_state["호텔_설정"]
if "호텔_표원본" not in st.session_state:
    st.session_state["호텔_표원본"] = [
        dict(r) for r in (설정.get("감시") or HT.기본_감시표())]
storage.임시서버_안내()


def _열쇠(이름, 기본=""):
    """secrets 또는 환경변수에서 값을 읽습니다. 없으면 기본값."""
    try:
        값 = st.secrets[이름]
        if 값 is not None and str(값).strip():
            return str(값).strip()
    except Exception:                                        # noqa: BLE001
        pass
    return (os.environ.get(이름.upper(), "") or "").strip() or 기본


RAPID키 = _열쇠("rapidapi_key")
호스트 = _열쇠("rapidapi_host", 설정.get("호스트") or HT.기본_호스트)
# ★ 아고다 키는 별도 값(agoda_key)이 있으면 그걸 쓰고, 없으면 부킹닷컴과
#   같은 RapidAPI 키를 재사용합니다 — RapidAPI 키는 보통 계정 하나에 API
#   여러 개를 구독하는 방식이라, 아고다도 같은 키로 구독했다면 그대로
#   동작합니다. 호스트만 API 마다 다릅니다.
아고다키 = _열쇠("agoda_key", RAPID키)
아고다호스트 = _열쇠("agoda_host", AG.기본_호스트)
텔레토큰 = _열쇠("telegram_token")
텔레방 = _열쇠("telegram_chat_id")
손님 = storage.손님인가()


def _채널묶음():
    """알림 채널 설정."""
    return {"텔레그램": {"토큰": 텔레토큰, "방": 텔레방}}


def _저장하기(조용히=True):
    """이력·상태가 바뀌었으면 바로 저장합니다.

    확인할 때마다 저장하는 이유 — 저장 버튼을 눌러야 남는다면 추이가
    안 쌓입니다. 그리고 자동 확인(GitHub Actions)이 이 자료를 읽으므로,
    화면에서 고친 조건이 저장돼 있어야 다음 자동 확인에 반영됩니다.
    """
    성공, 메시지 = storage.저장하기(저장키, 설정)
    if not 조용히:
        (st.success if 성공 else st.warning)(메시지)
    return 성공


# ==========================================================================
# 0. 준비 상태
# ==========================================================================
준비됨 = bool(RAPID키)
텔레준비 = bool(텔레토큰 and 텔레방)
알림준비 = 텔레준비

if not 준비됨:
    st.warning("**RapidAPI 키가 없어 가격을 조회할 수 없습니다.** "
               "아래 '처음 설정' 을 펼쳐 5분만 따라 하세요. "
               "키 없이도 가격을 직접 적어 넣으면 추이와 목표가 판정은 "
               "그대로 동작합니다.", icon="🔑")

with st.expander("🔧 처음 설정 (5분)", expanded=not 준비됨):
    st.markdown(f"""
##### 1단계 · RapidAPI 키 받기
1. [rapidapi.com](https://rapidapi.com) 가입 (무료)
2. **Booking.com** 으로 검색해서 API 하나를 고릅니다
   (기본값은 `{HT.기본_호스트}` 입니다)
3. **Subscribe** 를 누릅니다 — **무료 플랜도 구독을 눌러야** 동작합니다
4. 화면에 나오는 `X-RapidAPI-Key` 값을 복사

##### 2단계 · 텔레그램 봇 만들기
1. 텔레그램에서 **@BotFather** 를 찾아 `/newbot`
2. `123456:ABC…` 토큰을 받습니다
3. **만든 봇에게 아무 말이나 한 번 보냅니다** (이걸 빼먹으면 못 보냅니다)
4. 아래 '내 chat_id 찾기' 버튼을 누르면 id 가 나옵니다

##### 3단계 · 앱에 알려주기
- **내 PC** : `.streamlit/secrets.toml` 에 아래 내용 추가
- **Streamlit Cloud** : 앱 화면 `⋮ → Settings → Secrets` 칸에 붙여넣기

```toml
rapidapi_key = "여기에_복사한_RapidAPI_키"
rapidapi_host = "{HT.기본_호스트}"
telegram_token = "123456:여기에_봇_토큰"
telegram_chat_id = "여기에_chat_id"
```

> ⚠️ `secrets.toml` 은 **절대 GitHub 에 올리지 마세요.** `.gitignore` 에
> 이미 들어 있습니다. Cloud 에서는 파일을 만들지 말고 Settings → Secrets
> 칸에만 넣으세요.
""")
    if 텔레토큰:
        if st.button("🔎 내 chat_id 찾기", key="호텔_방찾기"):
            방들, 오류 = HT.텔레그램_채팅찾기(텔레토큰)
            if 오류:
                st.error(오류)
            else:
                st.dataframe(pd.DataFrame(방들), width="stretch",
                             hide_index=True)
                st.caption("위 `chat_id` 를 secrets 의 telegram_chat_id 에 넣으세요.")
    else:
        st.caption("봇 토큰(`telegram_token`)을 먼저 넣으면 chat_id 찾기 버튼이 "
                   "나타납니다.")

상태줄 = [
    ui.뱃지("RapidAPI 연결됨" if 준비됨 else "RapidAPI 키 없음",
          "좋음" if 준비됨 else "나쁨"),
    ui.뱃지("텔레그램 ✓" if 텔레준비 else "텔레그램 미설정",
          "좋음" if 텔레준비 else "중립"),
]
if 손님:
    상태줄.append(ui.뱃지("Guest — 조회·저장 안 됨", "나쁨"))
st.markdown(" ".join(상태줄), unsafe_allow_html=True)


# ==========================================================================
# 1. 감시 조건
# ==========================================================================
ui.섹션("무엇을 지켜볼까",
        "**아이 나이는 만 나이**를 쉼표로 적습니다 (예: `5, 8`). "
        "빈칸으로 두면 어른만 있는 가격이 나옵니다.", 라벨="1단계")

편집표 = st.data_editor(
    표만들기(st.session_state["호텔_표원본"] or HT.기본_감시표(), HT.감시열),
    num_rows="dynamic", width="stretch",
    key=f"호텔_감시_{st.session_state['호텔_표버전']}",
    # ★ '종류' 는 화면에 안 보여줍니다. 도시인지 호텔인지 구분하는
    #   내부 값이라 사람이 직접 적을 일이 없고, 잘못 적으면 조회가
    #   깨집니다. column_order 에서 빼면 표에는 안 보이지만
    #   data_editor 가 돌려주는 값에는 그대로 남습니다.
    column_order=[c for c in HT.감시열 if c not in ("종류", "아고다_id")],
    column_config={
        "사용": st.column_config.CheckboxColumn(
            "쓰기", width="small", help="끄면 자동 확인에서 뺍니다"),
        "이름": st.column_config.TextColumn(
            "감시 이름", width="medium",
            help="알림과 가격 이력을 묶는 열쇠입니다. "
                 "**한 번 정하면 바꾸지 마세요** — 바꾸면 그동안 쌓인 "
                 "가격 이력과 연결이 끊어집니다."),
        "도시": st.column_config.TextColumn(width="small",
                                          help="보기용입니다. 조회에는 dest_id 를 씁니다"),
        "dest_id": st.column_config.TextColumn(
            "도시번호", width="small",
            help="아래 '도시 번호 찾기' 에서 넣으세요. 이게 없으면 조회할 수 없습니다"),
        "호텔": st.column_config.TextColumn(
            "호텔 (일부만)", width="medium",
            help="비우면 **그 도시 최저가**를 봅니다. 특정 호텔을 보려면 "
                 "이름의 일부를 적으세요 (예: `Namba Oriental`)"),
        "체크인": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "체크아웃": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "어른": st.column_config.NumberColumn(
            "어른", min_value=1, max_value=30, step=1,
            help="만 18세부터는 어른으로 셉니다"),
        "아이나이": st.column_config.TextColumn(
            "아이 만나이", width="small",
            help="쉼표로 구분 (예: `5, 8`). ★ 기준은 오늘이 아니라 "
                 "**체크인 당일**입니다. 여행이 생일 뒤면 한 살 올려 적으세요"),
        "방수": st.column_config.NumberColumn("방", min_value=1, max_value=10,
                                            step=1),
        "목표가": st.column_config.NumberColumn(
            "목표가(총액)", min_value=0, step=10_000, format="localized",
            help="전체 숙박 **총액** 기준입니다. 이 값 이하로 내려가면 알립니다. "
                 "0 이면 목표가 조건을 쓰지 않습니다"),
        "하락률": st.column_config.NumberColumn(
            "하락 %", min_value=0, max_value=90, step=1,
            help="처음 본 값보다 이만큼 싸지면 알립니다. 0 이면 안 씁니다"),
        "무료취소만": st.column_config.CheckboxColumn(
            "무료취소만", width="small",
            help="켜면 무료취소가 안 되는(더 싼) 요금은 무시하고, 무료취소 "
                 "가능한 것 중에서만 최저가를 찾습니다. 대신 표시되는 "
                 "가격이 더 비싸질 수 있습니다. "
                 "**'호텔' 칸에 특정 호텔을 적어두면** 그 호텔의 방 목록을 "
                 "따로 조회해 확실하게 판정합니다(추정 아님). 호텔을 안 "
                 "적으면(도시 최저가 감시) 설명 문구로 짐작만 합니다. "
                 "무료취소 가능한 곳이 없으면 그렇게 표시하고, 가격은 "
                 "기록하지 않습니다."),
    })

새감시 = []
for _, row in 편집표.iterrows():
    이름 = str(row.get("이름") or "").strip()
    도시 = str(row.get("도시") or "").strip()
    아이디 = str(row.get("dest_id") or "").strip()
    if not 이름 and not 도시 and not 아이디:
        continue                              # 완전히 빈 줄은 버립니다
    새감시.append({
        "사용": bool(row.get("사용", True)),
        "이름": 이름,
        "도시": 도시,
        "dest_id": 아이디,
        # ★ 대문자로 바꾸면 안 됩니다. API 가 "hotel" 처럼 소문자로
        #   주는데 대문자로 바꿔 보내면 대소문자를 구분하는 API 에서는
        #   dest_id 가 맞아도 거부당합니다.
        "종류": str(row.get("종류") or "").strip(),
        "아고다_id": str(row.get("아고다_id") or "").strip(),
        "호텔": str(row.get("호텔") or "").strip(),
        "체크인": 날짜로(row.get("체크인")),
        "체크아웃": 날짜로(row.get("체크아웃")),
        "어른": int(숫자로(row.get("어른"), 2)) or 2,
        "아이나이": HT.아이나이_글자(row.get("아이나이")),
        "방수": int(숫자로(row.get("방수"), 1)) or 1,
        "목표가": 숫자로(row.get("목표가"), 0.0),
        "하락률": 숫자로(row.get("하락률"), 0.0),
        "무료취소만": bool(row.get("무료취소만", False)),
    })
설정["감시"] = 새감시


# --------------------------------------------------------------------------
# 도시 번호(dest_id) 찾아 넣기
# --------------------------------------------------------------------------
#  ★ 이 도우미는 표 **뒤에** 있어야 합니다.
#    표 앞에 두고 '이 줄에 넣기' 를 누르면, 표의 편집 내역을 아직 읽지 않은
#    상태에서 원본을 갈아치우게 되어 방금 손으로 고친 내용이 사라집니다.
#    여기서는 편집이 반영된 새감시 를 바탕으로 고쳐 넣습니다.
with st.expander("🔎 도시 번호(dest_id) 찾기", expanded=not any(
        r["dest_id"] for r in 새감시)):
    st.caption("예약 사이트는 도시를 이름이 아니라 번호로 구분합니다. "
               "사람이 외울 수 없는 값이라 여기서 찾아 넣습니다.")
    찾기1, 찾기2 = st.columns([3, 1])
    도시글 = 찾기1.text_input("도시 이름 (영어로 넣는 게 잘 찾습니다)",
                          value="", placeholder="Osaka / Seoul / Da Nang",
                          key="호텔_도시글")
    if 찾기2.button("🔎 찾기", width="stretch", key="호텔_도시찾기",
                  disabled=not 준비됨 or 손님):
        목록, 찾기오류 = HT.도시_찾기(도시글, RAPID키, 호스트)
        st.session_state["호텔_도시결과"] = 목록
        if 찾기오류:
            st.error(찾기오류)

    도시결과 = st.session_state.get("호텔_도시결과") or []
    if 도시결과:
        보기 = [f"{d['라벨'] or d['이름']}  ·  {d['종류']}"
              f"  ·  dest_id {d['dest_id']}" for d in 도시결과]
        고른번호 = st.selectbox("찾은 곳 중에서 고르세요", range(len(보기)),
                            format_func=lambda i: 보기[i], key="호텔_도시고름")
        고른도시 = 도시결과[min(고른번호, len(도시결과) - 1)]
        도시이름 = 고른도시["이름"] or 고른도시["라벨"] or "도시"

        ㄱ1, ㄱ2 = st.columns(2)
        줄이름 = [f"{i + 1}. {(r.get('이름') or '이름 없음')}"
                for i, r in enumerate(새감시)]
        대상 = ㄱ1.selectbox("어느 줄에 넣을까요",
                          range(len(줄이름)) if 줄이름 else [0],
                          format_func=(lambda i: 줄이름[i]) if 줄이름
                          else (lambda i: "(줄 없음)"),
                          key="호텔_대상줄", disabled=not 줄이름)
        if ㄱ1.button("↳ 이 줄에 넣기", width="stretch", key="호텔_넣기",
                    disabled=not 줄이름):
            새행들 = [dict(r) for r in 새감시]
            새행들[min(대상, len(새행들) - 1)]["dest_id"] = 고른도시["dest_id"]
            새행들[min(대상, len(새행들) - 1)]["도시"] = 도시이름
            # ★ 종류(search_type)도 함께 넣습니다. 이게 없으면 호텔 이름으로
            #   찾은 dest_id(대개 HOTEL 타입)를 CITY 로 조회하게 되어
            #   빈 결과가 돌아옵니다.
            새행들[min(대상, len(새행들) - 1)]["종류"] = 고른도시["종류"]
            _표원본_바꾸기(새행들)
            st.rerun()

        if ㄱ2.button("➕ 새 감시 줄로 추가", width="stretch", key="호텔_새줄"):
            들어감 = date.today() + timedelta(days=60)
            새행들 = [dict(r) for r in 새감시]
            새행들.append({
                "사용": True,
                "이름": f"{도시이름} 여행",
                "도시": 도시이름,
                "dest_id": 고른도시["dest_id"],
                "종류": 고른도시["종류"],
                "호텔": "",
                "체크인": 들어감,
                "체크아웃": 들어감 + timedelta(days=2),
                "어른": 2, "아이나이": "", "방수": 1,
                "목표가": 0, "하락률": 10,
            })
            _표원본_바꾸기(새행들)
            st.rerun()

# --------------------------------------------------------------------------
# 아고다 id 찾아 넣기 (선택) — 넣어 두면 그 줄은 부킹닷컴·아고다를 함께
# 조회해 더 싼 쪽을 씁니다. 안 넣으면 지금까지처럼 부킹닷컴만 봅니다.
# --------------------------------------------------------------------------
with st.expander("🅰️ 아고다도 함께 비교하기 (선택)", expanded=False):
    st.caption("여기서 찾은 값을 넣어 두면, 그 줄은 부킹닷컴과 아고다 중 "
               "**더 싼 쪽**을 골라 보여줍니다. 안 넣어도 부킹닷컴만으로 "
               "그대로 동작합니다.")
    아찾기1, 아찾기2 = st.columns([3, 1])
    아고다글 = 아찾기1.text_input("도시/호텔 이름 (영어)", value="",
                              placeholder="Singapore / Carlton Hotel Singapore",
                              key="호텔_아고다글")
    if 아찾기2.button("🔎 찾기", width="stretch", key="호텔_아고다찾기",
                    disabled=not 아고다키 or 손님):
        아목록, 아찾기오류 = AG.도시_찾기(아고다글, 아고다키, 아고다호스트)
        st.session_state["호텔_아고다결과"] = 아목록
        if 아찾기오류:
            st.error(아찾기오류)

    아고다결과 = st.session_state.get("호텔_아고다결과") or []
    if 아고다결과:
        아보기 = [f"{d['라벨'] or d['이름']}  ·  {d['typeName'] or d['typeId']}"
                f"  ·  id {AG.합친_id(d['typeId'], d['place_id'])}"
                for d in 아고다결과]
        아고른번호 = st.selectbox("찾은 곳 중에서 고르세요", range(len(아보기)),
                             format_func=lambda i: 아보기[i], key="호텔_아고다고름")
        아고른곳 = 아고다결과[min(아고른번호, len(아고다결과) - 1)]
        아합친id = AG.합친_id(아고른곳["typeId"], 아고른곳["place_id"])

        아줄이름 = [f"{i + 1}. {(r.get('이름') or '이름 없음')}"
                 for i, r in enumerate(새감시)]
        아대상 = st.selectbox("어느 줄에 넣을까요",
                          range(len(아줄이름)) if 아줄이름 else [0],
                          format_func=(lambda i: 아줄이름[i]) if 아줄이름
                          else (lambda i: "(줄 없음)"),
                          key="호텔_아고다대상줄", disabled=not 아줄이름)
        if st.button("↳ 이 줄에 아고다_id 넣기", width="stretch",
                    key="호텔_아고다넣기", disabled=not 아줄이름):
            새행들 = [dict(r) for r in 새감시]
            대상줄이름 = 새행들[min(아대상, len(새행들) - 1)].get("이름") or "이 줄"
            새행들[min(아대상, len(새행들) - 1)]["아고다_id"] = 아합친id
            _표원본_바꾸기(새행들)
            # ★ 아고다_id 는 표에서 숨겨진 칸이라 넣어도 눈에 안 보입니다.
            #   방금 어느 줄에 무슨 값이 들어갔는지 확인할 방법이 없으면
            #   사용자가 "도시번호(dest_id)" 칸에 잘못 옮겨 적는 사고가
            #   납니다(실제로 있었던 일입니다) — 그래서 반드시 알려줍니다.
            st.session_state["호텔_아고다_넣은결과"] = (대상줄이름, 아합친id)
            st.rerun()

    넣은결과 = st.session_state.get("호텔_아고다_넣은결과")
    if 넣은결과:
        st.success(f"✅ **{넣은결과[0]}** 줄에 아고다_id `{넣은결과[1]}` 를 "
                   "넣었습니다. (표의 '도시번호' 칸과는 다른, 숨겨진 값입니다 "
                   "— 그 칸은 그대로 두세요.)")

정리목록 = [HT.행_정리(r) for r in 새감시]

# 이름이 겹치면 이력이 섞입니다. 조회 전에 잡아줍니다.
이름들 = [p["이름"] for p in 정리목록]
겹침 = sorted({n for n in 이름들 if 이름들.count(n) > 1})
if 겹침:
    st.error(f"**감시 이름이 겹칩니다: {', '.join(겹침)}** — 이름은 가격 이력을 "
             "묶는 열쇠라서 서로 달라야 합니다. 다르게 고쳐 주세요.", icon="🔁")

못하는것 = [(p, HT.부족한것(p)) for p in 정리목록]
조회가능 = [p for p, 빠짐 in 못하는것 if not 빠짐]
if not 겹침:
    for p, 빠짐 in 못하는것:
        if 빠짐:
            st.caption(f"⚠️ **{p['이름']}** — 아직 조회 못 함: {', '.join(빠짐)}")

# ★ 아고다_id 는 표에서 숨겨진 칸이라 넣었는지 안 넣었는지 표만 봐서는
#   알 수 없습니다. 넣은 줄이 하나라도 있으면 여기서 보여줘서, 방금 넣기
#   버튼을 눌렀을 때 정말 반영됐는지 확인할 수 있게 합니다.
아고다_켜진줄 = [p["이름"] for p in 정리목록 if p.get("아고다_id")]
if 아고다_켜진줄:
    st.caption("🅰️ 아고다도 함께 비교하는 줄: " + ", ".join(아고다_켜진줄))

ㅅ1, ㅅ2, ㅅ3 = st.columns(3)
통화 = ㅅ1.selectbox("통화", 통화목록,
                  index=고른위치(통화목록, 설정.get("통화"), 0), key="호텔_통화")
주기 = ㅅ2.selectbox("자동 확인 주기", 주기목록,
                  index=고른위치(주기목록, int(숫자로(설정.get("주기"), 6)), 1),
                  format_func=lambda h: f"{h}시간마다", key="호텔_주기")
알림켬 = ㅅ3.toggle("알림 보내기", value=bool(설정.get("알림켬", True)),
                 key="호텔_알림켬",
                 help="끄면 가격만 기록하고 알림은 보내지 않습니다")
설정["통화"] = 통화
설정["주기"] = int(주기)
설정["알림켬"] = bool(알림켬)
설정["호스트"] = 호스트


# ==========================================================================
# 3. 지금 확인
# ==========================================================================
ui.섹션("지금 한 번 확인", "자동 확인과 별개로, 지금 값을 보고 이력에 남깁니다.",
        라벨="2단계")

ㅎ1, ㅎ2 = st.columns([2, 1])
누름 = ㅎ1.button(f"🔍 지금 확인 ({len(조회가능)}건)", type="primary",
               width="stretch", key="호텔_확인",
               disabled=not (준비됨 and 조회가능) or bool(겹침) or 손님)
테스트 = ㅎ2.button("📨 알림 테스트", width="stretch", key="호텔_테스트",
                 disabled=not 알림준비)

if 손님:
    st.caption("👤 Guest 는 조회할 수 없습니다. 주인의 RapidAPI 호출 한도를 "
               "쓰게 되기 때문입니다. 사이드바에서 Master 로 전환하세요.")

if 테스트:
    수, 결과목록, _새것 = HT.알림_보내기(
        _채널묶음(),
        "🏨 <b>호텔 가격 알림 테스트</b>\n설정이 정상입니다. "
        "조건에 맞는 가격이 나오면 이렇게 알려드립니다.")
    for 채널이름, 좋음, 말 in 결과목록:
        (st.success if 좋음 else st.error)(f"**{채널이름}** — {말}")
    if not 결과목록:
        st.warning("보낼 채널이 없습니다.")

if 누름:
    이력 = list(설정.get("이력") or [])
    상태 = dict(설정.get("상태") or {})
    결과들 = {}
    진행 = st.progress(0.0, text="확인 중…")
    보낼것 = []
    for i, p in enumerate(조회가능):
        진행.progress(min(max((i + 1) / len(조회가능), 0.0), 1.0),
                    text=f"{p['이름']} 확인 중…")
        답 = HT.한줄_확인(p, 상태, 이력, RAPID키, 호스트, 통화,
                       아고다키, 아고다호스트)
        이력 = 답["새이력"]
        상태[p["이름"]] = 답["새상태"]
        결과들[p["이름"]] = {
            "최저가": 답["최저가"], "호텔": 답["호텔"], "오류": 답["오류"],
            "판정": 답["판정"], "요약": 답["요약"],
            "무료취소": 답.get("무료취소", "모름"),
            "세금포함": 답.get("세금포함", False),
            "사이트": 답.get("사이트", ""),
            "후보": 답["목록"][:8], "원본있음": 답["원본"] is not None,
        }
        if 답["판정"] and 답["판정"]["알림"]:
            보낼것.append((p, 답))
    진행.empty()

    설정["이력"] = 이력
    설정["상태"] = 상태
    st.session_state["호텔_결과"] = 결과들

    보낸수 = 0
    if 알림켬 and 알림준비:
        채널 = _채널묶음()
        보낸채널 = set()
        for p, 답 in 보낼것:
            수, 결과목록, _새것 = HT.알림_보내기(
                채널,
                HT.알림_문장(p, 답["최저가"], 답["판정"], 답["요약"],
                          답.get("무료취소", "모름"),
                          답.get("세금포함", False),
                          답.get("사이트", "")))
            보낸수 += 수
            for 채널이름, 좋음, 말 in 결과목록:
                if 좋음:
                    보낸채널.add(채널이름)
                else:
                    st.warning(f"{p['이름']} → {채널이름} 실패: {말}")
            if 수 == 0:
                # 어느 채널로도 못 갔으면 '알렸다' 기록을 지워 다음에 재시도
                기록 = 상태.get(p["이름"]) or {}
                기록.pop("마지막알림가", None)
                기록.pop("마지막알림일", None)
                상태[p["이름"]] = 기록
                설정["상태"] = 상태
    elif 보낼것:
        st.info(f"조건에 맞는 것이 {len(보낼것)}건 있지만 알림은 보내지 않았습니다 "
                + ("(알림 끔)" if not 알림켬 else "(알림 채널 미설정)"), icon="🔕")

    if 보낸수:
        st.success(f"{' · '.join(sorted(보낸채널))} 로 {보낸수}건 보냈습니다.",
                   icon="📨")
    if not 손님:
        _저장하기()

    # ★ 여기서 st.rerun() 을 부르면 안 됩니다.
    #   방금 그린 성공·경고 안내가 전부 지워져서, 알림을 보냈는지 실패했는지
    #   화면에 아무것도 안 남습니다. 그리고 필요도 없습니다 — 결과를 그리는
    #   구역이 이 아래에 있어서, 이번 실행에서 그대로 새 값으로 그려집니다.


# ==========================================================================
# 4. 결과 · 가격 추이
# ==========================================================================
결과들 = st.session_state.get("호텔_결과") or {}
이력 = 설정.get("이력") or []
상태 = 설정.get("상태") or {}

# ★ 이름이 겹치면 아래에서 같은 위젯 key 를 두 번 만들게 되어
#   StreamlitDuplicateElementKey 로 페이지가 통째로 죽습니다. 위에서 경고는
#   띄웠지만, 고치기 전까지 화면이 살아 있어야 고칠 수 있으므로
#   먼저 나온 것만 그립니다.
볼것, 본이름 = [], set()
for p in 정리목록:
    if not p["이름"] or p["이름"] in 본이름:
        continue
    본이름.add(p["이름"])
    볼것.append(p)

if 볼것:
    ui.섹션("가격 추이", "확인할 때마다 하루 한 점씩 쌓입니다. "
            "같은 날 여러 번 확인하면 **더 싼 값**이 남습니다.", 라벨="결과")

for p in 볼것:
    이름 = p["이름"]
    요약 = HT.이력_요약(이력, 이름)
    결과 = 결과들.get(이름) or {}
    저장상태 = HT.기억_읽기(상태, 이름)
    현재가 = 숫자로(결과.get("최저가"), 0.0) or 요약["최근"]
    기준가 = HT.기준가_정하기(p, 이력, 저장상태.get("기준가"))

    제목 = f"🏨 {이름}"
    if 현재가 > 0:
        제목 += f" — {현재가:,.0f}원"
    with st.expander(제목, expanded=len(볼것) <= 3):
        st.caption(f"{HT.일정_설명(p)} · {p['인원글']}"
                   + (f" · {p['호텔']}" if p["호텔"] else " · 도시 최저가"))

        if 결과.get("오류"):
            st.error(결과["오류"], icon="⚠️")

        판정 = 결과.get("판정")
        if 현재가 > 0:
            뱃지들 = []
            if 판정 and 판정.get("목표달성"):
                뱃지들.append(ui.뱃지("목표가 달성", "좋음"))
            if 판정 and 판정.get("하락달성"):
                뱃지들.append(ui.뱃지(f"{판정['하락폭']:.1f}% 하락", "좋음"))
            if 요약["횟수"] > 1 and 현재가 <= 요약["최저"]:
                뱃지들.append(ui.뱃지("역대 최저", "강조"))
            if 판정 and 판정.get("보류"):
                뱃지들.append(ui.뱃지("알림 보류", "중립"))
            # ★ 무료취소 여부는 가격을 해석하는 데 중요합니다. 같은 호텔도
            #   무료취소가 안 되는 요금이 훨씬 싸서, 이걸 안 보면 "싸졌다"
            #   가 사실은 "환불 안 되는 요금으로 바뀌었다" 일 수 있습니다.
            무료취소 = 결과.get("무료취소", "모름")
            뱃지들.append(ui.뱃지(
                {"가능": "무료취소 가능", "불가": "무료취소 불가(추정)"}.get(
                    무료취소, "무료취소 확인 필요"),
                {"가능": "좋음", "불가": "나쁨"}.get(무료취소, "중립")))
            사이트 = 결과.get("사이트", "")
            if 사이트:
                뱃지들.append(ui.뱃지(
                    {"부킹닷컴": "🅱️ 부킹닷컴", "아고다": "🅰️ 아고다"}.get(
                        사이트, 사이트), "중립"))
            세금포함 = 결과.get("세금포함", False)
            한박 = (f"1박당 약 {현재가 / p['밤수']:,.0f}원" if p["밤수"] else "")
            표시_라벨 = ("지금 가장 싼 값 (세금 포함)" if 세금포함
                     else "지금 가장 싼 값")
            ui.헤드라인(표시_라벨, f"{현재가:,.0f}원", 한박, 뱃지들)
            if 결과.get("호텔"):
                st.caption(f"해당 호텔: **{결과['호텔']}**")
            if not 세금포함:
                st.caption("ℹ️ 세금·수수료를 이번엔 확인하지 못했습니다. "
                           "실제 결제액이 더 클 수 있습니다.")
            if 무료취소 == "모름":
                st.caption("ℹ️ 무료취소 여부를 응답에서 읽지 못했습니다. "
                           "예약 전 사이트에서 꼭 확인하세요.")

            카드들 = []
            if p["목표가"] > 0:
                남음 = 현재가 - p["목표가"]
                카드들.append(("목표가", f"{p['목표가']:,.0f}원",
                            "달성" if 남음 <= 0 else f"{남음:,.0f}원 더 내려야",
                            "초록" if 남음 <= 0 else "주황"))
            if 기준가 > 0:
                # 내려간 것을 음수로 보여줍니다. 금액과 % 의 부호가
                # 어긋나면(-40,000원인데 +13%) 읽는 사람이 헷갈립니다.
                변화 = 현재가 - 기준가
                비율 = 변화 / 기준가 * 100
                카드들.append(("처음 본 값", f"{기준가:,.0f}원",
                            f"{변화:+,.0f}원 ({비율:+.1f}%)",
                            "초록" if 변화 < 0 else
                            ("빨강" if 변화 > 0 else "회색")))
            if 요약["횟수"] > 1:
                카드들.append(("지금까지 최저", f"{요약['최저']:,.0f}원",
                            f"{요약['횟수']}회 확인", "파랑"))
                카드들.append(("지금까지 최고", f"{요약['최고']:,.0f}원", "", "회색"))
            if 카드들:
                ui.카드_줄(카드들, 열수=2)

            if p["목표가"] > 0 and 현재가 > 0:
                # 목표가까지 얼마나 왔나. 기준가에서 목표가까지를 100% 로 봅니다.
                폭 = max(기준가 - p["목표가"], 1.0)
                진척 = (기준가 - 현재가) / 폭
                st.progress(min(max(진척, 0.0), 1.0),
                            text=f"처음 본 값에서 목표가까지 {진척 * 100:.0f}%")
        elif not 결과.get("오류"):
            st.info("아직 확인한 적이 없습니다. 위 '지금 확인' 을 누르거나, "
                    "아래에서 직접 본 가격을 적어 넣으세요.", icon="📝")

        # ---- 추이 차트 ----
        if 요약["횟수"] >= 2:
            점들 = 요약["점들"]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[d for d, _ in 점들], y=[v for _, v in 점들],
                mode="lines+markers", name="가격",
                line=dict(color=ui.색["파랑"], width=2),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}원<extra></extra>"))
            if p["목표가"] > 0:
                fig.add_hline(y=p["목표가"], line_dash="dash",
                              line_color=ui.색["초록"],
                              annotation_text=f"목표 {p['목표가']:,.0f}원",
                              annotation_position="top left")
            if 기준가 > 0:
                fig.add_hline(y=기준가, line_dash="dot",
                              line_color=ui.색["주황"],
                              annotation_text="처음 본 값",
                              annotation_position="bottom left")
            fig.update_layout(height=260, showlegend=False,
                              margin=dict(l=0, r=0, t=10, b=0),
                              yaxis_title="원", xaxis_title="")
            ui.차트(fig, key=f"호텔_차트_{이름}")
        elif 요약["횟수"] == 1:
            st.caption("점이 하나뿐이라 아직 선을 그릴 수 없습니다. "
                       "두 번 이상 확인하면 추이가 나옵니다.")

        # ---- 그 도시의 다른 후보 ----
        후보 = 결과.get("후보") or []
        if 후보 and not p["호텔"]:
            with st.expander(f"이 조건에서 싼 곳 {len(후보)}개 보기"):
                st.dataframe(pd.DataFrame([{
                    "호텔": h["호텔"], "총액(원)": round(h["가격"]),
                    "1박당": round(h["가격"] / p["밤수"]) if p["밤수"] else 0,
                    "무료취소": {"가능": "🟢 가능", "불가": "🔴 불가(추정)"}.get(
                        h.get("무료취소", "모름"), "⚪ 확인 필요"),
                    "사이트": {"부킹닷컴": "🅱️", "아고다": "🅰️"}.get(
                        h.get("사이트", ""), h.get("사이트", "")),
                } for h in 후보]).style.format(
                    {"총액(원)": "{:,}", "1박당": "{:,}"}),
                    width="stretch", hide_index=True)
                st.caption("무료취소 표시는 API 설명 문구에서 추정한 값이라 "
                           "100% 정확하지 않습니다 — 예약 전 사이트에서 확인하세요. "
                           "특정 호텔만 지켜보려면 위 표의 '호텔' 칸에 이름의 "
                           "일부를 적으세요.")

        # ---- 직접 적어 넣기 ----
        with st.expander("✍️ 예약 사이트에서 본 가격 직접 넣기"):
            st.caption("API 값이 실제와 다를 때, 또는 키가 없을 때 씁니다. "
                       "적어 넣은 값도 추이와 목표가 판정에 함께 쓰입니다. "
                       "무료취소 여부는 따로 기록되지 않으니, 예약 사이트에서 "
                       "직접 다시 확인하세요.")
            ㅈ1, ㅈ2, ㅈ3 = st.columns([1.2, 1, 1])
            그날 = ㅈ1.date_input("본 날짜", value=date.today(),
                              key=f"호텔_수동일_{이름}")
            값 = ㅈ2.number_input("총액(원)", min_value=0, step=10_000, value=0,
                               key=f"호텔_수동값_{이름}")
            if ㅈ3.button("추가", width="stretch", key=f"호텔_수동추가_{이름}",
                        disabled=손님):
                if 값 <= 0:
                    st.warning("0원은 넣을 수 없습니다.")
                else:
                    설정["이력"] = HT.기록_추가(설정.get("이력") or [], 이름, 값,
                                          p["호텔"] or "직접 입력", 그날)
                    _저장하기()
                    st.rerun()


# ==========================================================================
# 5. 자동으로 지켜보기 (GitHub Actions)
# ==========================================================================
ui.섹션("자동으로 지켜보기", "이 페이지를 닫아도, 앱이 잠들어도 계속 확인합니다.",
        라벨="3단계")

with st.expander("⏰ 자동 확인 켜는 방법", expanded=False):
    st.markdown(f"""
Streamlit 은 **아무도 안 보면 잠듭니다.** 잠든 앱은 가격을 확인할 수 없어서,
자동 확인은 GitHub Actions 가 대신 돌립니다. 무료이고, 앱이 자든 말든 돕니다.

##### 1단계 · 파일 두 개를 저장소에 올립니다
이미 만들어 뒀습니다. 그대로 올리면 됩니다.
- `scripts/hotel_check.py` — 가격을 확인하고 알림을 보내는 프로그램
- `.github/workflows/hotel-watch.yml` — **{주기}시간마다** 위 프로그램을 실행

##### 2단계 · 저장소에 열쇠를 넣습니다
GitHub 저장소 → **Settings → Secrets and variables → Actions**
→ **New repository secret** 으로 아래를 하나씩 추가합니다.

| 이름 | 값 |
|---|---|
| `RAPIDAPI_KEY` | RapidAPI 키 |
| `RAPIDAPI_HOST` | `{HT.기본_호스트}` |
| `TELEGRAM_TOKEN` | 봇 토큰 |
| `TELEGRAM_CHAT_ID` | chat_id |
| `GIST_TOKEN` | gist 권한 토큰 (아래 설명) |
| `GIST_ID` | 자료가 들어 있는 Gist id |

> Actions Secrets 는 저장소 코드에 안 남고, 로그에도 `***` 로 가려집니다.
> `secrets.toml` 파일을 올리는 것과 전혀 다릅니다.
>
> 이름이 `GITHUB_GIST_TOKEN` 이 아니라 `GIST_TOKEN` 인 이유 — GitHub 은
> `GITHUB_` 으로 시작하는 Secret 을 만들지 못하게 막아 두었습니다.
> 또 Actions 가 기본으로 주는 토큰은 Gist 에 접근할 수 없어서,
> **gist 권한만 준 개인 토큰**이 따로 필요합니다
> (`storage.py` 맨 위 1단계와 같은 토큰을 쓰면 됩니다).

##### 3단계 · Gist 설정이 반드시 필요합니다
자동 확인은 **감시 조건을 Gist 에서 읽고, 확인한 가격을 Gist 에 씁니다.**
그래서 이 페이지와 자동 확인이 같은 자료를 봅니다.
Gist 설정이 없으면 자동 확인은 감시 조건을 찾을 수 없습니다.
설정 방법은 `외부접속_설정_가이드.md` 또는 `storage.py` 맨 위 설명을 보세요.

현재 이 앱의 저장 방식: **{'GitHub Gist ✅' if storage.저장방식() == 'gist'
                          else '로컬 파일 — 자동 확인 전에 Gist 설정이 필요합니다'}**

##### 4단계 · 확인
저장소의 **Actions** 탭 → `호텔 가격 감시` → **Run workflow** 로
한 번 직접 돌려 보세요. 성공하면 이후로는 알아서 돕니다.
""")
    if storage.저장방식() != "gist":
        st.warning("지금은 로컬 파일에 저장하고 있습니다. 이대로는 자동 확인이 "
                   "감시 조건을 읽을 수 없습니다. 먼저 Gist 를 설정하세요.",
                   icon="☁️")

with st.expander("🧪 응답 원본 보기 (값이 이상할 때)"):
    st.caption("비공식 API 라서 응답 구조가 바뀔 수 있습니다. 가격을 못 읽거나 "
               "엉뚱한 값이 나오면 여기서 원본을 확인하세요.")
    if not 준비됨:
        st.caption("RapidAPI 키가 없어 조회할 수 없습니다.")
    elif not 조회가능:
        st.caption("조회 가능한 감시 줄이 없습니다.")
    else:
        보기이름 = [p["이름"] for p in 조회가능]
        고름 = st.selectbox("어느 줄", range(len(보기이름)),
                          format_func=lambda i: 보기이름[i], key="호텔_원본줄")
        if st.button("원본 가져오기", key="호텔_원본", disabled=손님):
            목록, 오류, 원본 = HT.호텔_검색(조회가능[고름], RAPID키, 호스트, 통화)
            if 오류:
                st.error(오류)
            st.caption(f"해석된 항목: {len(목록)}개")
            if 목록:
                st.dataframe(pd.DataFrame(목록[:20]), width="stretch",
                             hide_index=True)
            st.json(원본, expanded=False)


# ==========================================================================
# 6. 쌓인 이력 관리
# ==========================================================================
if 이력:
    with st.expander(f"📒 쌓인 가격 이력 전체 ({len(이력)}줄)"):
        # ★ 날짜가 읽히지 않는 줄(None)이 섞이면 sort_values 가
        #   TypeError 로 죽습니다. None 과 date 를 비교할 수 없기 때문입니다.
        #   정렬은 문자열로 하고, 읽을 수 없는 날짜는 빈칸으로 둡니다.
        줄들 = []
        for r in 이력:
            그날 = 날짜로(r.get("날짜"))
            줄들.append({
                "감시": str(r.get("이름") or ""),
                "날짜": 그날.isoformat() if 그날 else "",
                "가격": 숫자로(r.get("가격"), 0.0),
                "호텔": str(r.get("호텔") or ""),
            })
        표 = pd.DataFrame(줄들).sort_values(["감시", "날짜"],
                                          kind="stable")
        st.dataframe(표.style.format({"가격": "{:,.0f}"}),
                     width="stretch", hide_index=True)

        남은이름 = {p["이름"] for p in 정리목록}
        고아 = sorted({str(r.get("이름")) for r in 이력} - 남은이름)
        if 고아:
            st.caption(f"지금 감시 목록에 없는 이력: {', '.join(고아)} — "
                       "감시 이름을 바꾸면 이렇게 끊어집니다.")
        ㅁ1, ㅁ2 = st.columns(2)
        if 고아 and ㅁ1.button("🧹 끊어진 이력 지우기", width="stretch",
                            key="호텔_고아정리", disabled=손님):
            설정["이력"] = [r for r in 이력
                        if str(r.get("이름")) in 남은이름]
            _저장하기()
            st.rerun()
        if ㅁ2.button("🗑️ 이력 전부 비우기", width="stretch", key="호텔_이력비움",
                    disabled=손님):
            설정["이력"] = []
            설정["상태"] = {}
            st.session_state["호텔_결과"] = {}
            _저장하기()
            st.rerun()


# ==========================================================================
# 7. 저장
# ==========================================================================
저장_불러오기(저장키, 설정, "호텔감시", "_호텔_적용대기",
          도움말="감시 조건과 쌓인 가격 이력이 함께 저장됩니다. "
               "자동 확인(GitHub Actions)도 이 자료를 읽습니다.")

st.divider()
st.caption("⚠️ 여기 나오는 값은 비공식 API 에서 온 참고값입니다. 세금·수수료 "
           "포함 여부가 예약 화면과 다를 수 있으니, 알림을 받으면 **실제 "
           "예약 사이트에서 다시 확인**하세요.")
