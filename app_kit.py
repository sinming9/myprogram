"""
==========================================================================
app_kit - 새 프로그램을 추가할 때 쓰는 도구 모음
==========================================================================
직접 만든 프로그램을 이 대시보드에 넣을 때, 로그인·모바일 대응·저장 같은
공통 처리를 한 줄로 끝내기 위한 모듈입니다.

[사용법]  pages/ 폴더에 파일을 만들고 맨 위에 아래 세 줄만 넣으세요.

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_kit import *          # noqa

    시작("자동차 유지비", "🚗", "연비와 주행거리로 월 유지비를 계산합니다")

    # ---- 여기서부터 자유롭게 작성 ----
    import streamlit as st
    거리 = st.number_input("월 주행거리(km)", value=1000)
    st.metric("예상 유류비", 원(거리 / 12 * 1700))

더 간단하게, 화면 파일을 만들지 않고 함수 하나만 쓰고 싶으면
myapps/ 폴더 사용법을 보세요 (myapps/예제_적금_계산기.py 참고).
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-08-02i"


import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

import storage
import ui
from auth import require_login, 로그아웃_버튼

__all__ = [
    "시작", "날짜로", "숫자로", "정수로", "표만들기", "저장_불러오기",
    "원", "만원", "억", "카드", "카드_줄",
    "저장", "불러오기", "백업_사이드바",
    "st", "pd", "ui", "storage", "date", "datetime",
]

# 자주 쓰는 표시 함수들을 그대로 노출
원 = ui.원
만원 = ui.만원
억 = ui.억
카드 = ui.카드
카드_줄 = ui.카드_줄
저장 = storage.저장하기
불러오기 = storage.불러오기
백업_사이드바 = storage.백업_사이드바


def 시작(제목: str, 아이콘: str = "📄", 부제: str = "",
        layout: str = "centered", 제목표시: bool = True):
    """페이지 맨 위에서 한 번 호출. 로그인 확인 + 모바일 대응 + 제목까지 처리."""
    require_login(page_title=제목, page_icon=아이콘, layout=layout)
    ui.모바일_스타일()
    로그아웃_버튼()
    ui.테마_안내()
    if 제목표시:
        st.title(f"{아이콘} {제목}")
        if 부제:
            st.caption(부제)
    storage.임시서버_안내()


# ==========================================================================
# 값 변환 도우미
#   st.data_editor 가 돌려주는 값은 pandas 버전과 컬럼 종류에 따라
#   date / datetime / Timestamp / 문자열 / NaT / None 이 섞여서 옵니다.
#   아래 함수들로 감싸서 쓰면 어떤 형태가 와도 안전합니다.
# ==========================================================================

최소_연도 = 1990
최대_연도 = 2100

# 문자열로 들어온 날짜는 "연(4자리)-월-일" 이 모두 있는 형태만 받습니다.
#   "2026"      → 1월 1일로 조용히 바뀌는 것을 막기 위해 거부
#   "26-05-20"  → 2020-05-26 처럼 엉뚱하게 해석되는 것을 막기 위해 거부
_완전한_날짜 = re.compile(r"^\s*(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})"
                     r"(?:[\sT].*)?\s*$")
_숫자8자리 = re.compile(r"^\s*(\d{4})(\d{2})(\d{2})\s*$")


def 날짜로(값, 최소=최소_연도, 최대=최대_연도):
    """어떤 형태의 값이든 datetime.date 로. 읽을 수 없으면 None.

    연도가 최소~최대 밖이면 잘못 입력한 것으로 보고 None 을 돌려줍니다.
    (예: '26-05-20' 처럼 두 자리 연도가 엉뚱하게 해석되는 경우 차단)
    """
    if 값 is None:
        return None
    try:
        if pd.isna(값):
            return None
    except (TypeError, ValueError):
        pass

    결과 = None
    if isinstance(값, pd.Timestamp):
        결과 = 값.date()
    elif isinstance(값, datetime):
        결과 = 값.date()
    elif isinstance(값, date):
        결과 = 값
    else:
        글자 = str(값)
        맞음 = _완전한_날짜.match(글자) or _숫자8자리.match(글자)
        if not 맞음:
            return None            # 애매한 문자열은 추측하지 않고 거부
        try:
            연, 월, 일 = (int(맞음.group(1)), int(맞음.group(2)), int(맞음.group(3)))
            결과 = date(연, 월, 일)
        except ValueError:
            결과 = None            # 2026-02-30 처럼 없는 날짜

    if 결과 is None:
        return None
    if not (최소 <= 결과.year <= 최대):
        return None
    return 결과


def 숫자로(값, 기본=0.0):
    """콤마·공백·'원' 이 섞인 값도 float 로. 못 읽으면 기본값."""
    if 값 is None:
        return 기본
    try:
        if pd.isna(값):
            return 기본
    except (TypeError, ValueError):
        pass
    if isinstance(값, (int, float)):
        return float(값)
    글자 = str(값).replace(",", "").replace(" ", "").replace("원", "").strip()
    if not 글자:
        return 기본
    try:
        return float(글자)
    except ValueError:
        return 기본


def 정수로(값, 기본=0):
    return int(round(숫자로(값, 기본)))


def 표만들기(자료목록, 열정의):
    """st.data_editor 에 넣을 DataFrame 을 안전한 dtype 으로 만듭니다.

    열정의 = {"날짜": "date", "금액": "number", "메모": "text", "사용": "bool"}

    ※ '날짜' 열을 datetime64 로 두면 pandas 3.x 에서 편집이 반영되지 않습니다.
      (DateColumn 은 datetime.date 를 돌려주는데 datetime64 열에 넣으면 TypeError)
      그래서 날짜 열은 반드시 object dtype + datetime.date 로 유지합니다.
    """
    df = pd.DataFrame(자료목록 or [])
    for 열, 종류 in 열정의.items():
        if 열 not in df.columns:
            df[열] = None
        if 종류 == "date":
            df[열] = pd.Series([날짜로(v) for v in df[열]], dtype="object")
        elif 종류 == "number":
            df[열] = pd.to_numeric(df[열], errors="coerce")
        elif 종류 == "bool":
            df[열] = df[열].fillna(False).astype(bool)
        else:
            df[열] = df[열].astype("object").where(df[열].notna(), "")
    return df[list(열정의)]


# ==========================================================================
# 저장 / 불러오기 구역  (모든 페이지에서 같은 모양)
# ==========================================================================

def 저장_불러오기(저장키: str, 현재값, 파일접두: str, 적용대기키: str,
              파일해석=None, 도움말: str = ""):
    """페이지 맨 아래에 붙이는 공통 저장·불러오기 구역.

    저장키     : storage 에 쓸 키 (예: "loan", "property_tax")
    현재값     : 지금 화면의 설정 (JSON 으로 만들 수 있는 값)
    파일접두   : 내려받을 파일 이름 앞부분 (예: "대출계산기_설정")
    적용대기키 : 올린 파일을 담아둘 session_state 키.
                페이지 맨 위에서 꺼내 적용해야 합니다.
                (위젯이 만들어진 뒤에 값을 바꾸면 Streamlit 이 막습니다)
    파일해석   : 올린 파일을 해석하는 함수. (파일) -> (데이터, 오류메시지)
                없으면 그냥 JSON 으로 읽습니다.
    """
    import json
    from datetime import date as _date

    st.divider()
    st.subheader("💾 저장 / 불러오기")

    c1, c2 = st.columns(2)
    if c1.button("💾 이 설정을 기본값으로 저장", type="primary",
                 width="stretch", key=f"_저장버튼_{저장키}"):
        성공, 메시지 = storage.저장하기(저장키, 현재값)
        (st.success if 성공 else st.error)(메시지)

    c2.download_button(
        "⬇️ 설정 파일 내려받기",
        data=json.dumps(현재값, ensure_ascii=False, indent=2, default=str),
        file_name=f"{파일접두}_{_date.today().isoformat()}.json",
        mime="application/json",
        width="stretch",
        key=f"_내려받기_{저장키}",
    )

    올린것 = st.file_uploader("⬆️ 설정 파일 올리기", type=["json"],
                           key=f"_업로드_{저장키}")
    if 올린것 is not None:
        if st.button("올린 설정 적용", width="stretch", key=f"_적용_{저장키}"):
            if 파일해석:
                데이터, 오류 = 파일해석(올린것)
            else:
                try:
                    데이터, 오류 = json.load(올린것), None
                except Exception as e:  # noqa: BLE001
                    데이터, 오류 = None, f"파일을 읽을 수 없습니다 ({e})"
            if 오류:
                st.error(f"불러오기 실패: {오류}")
            else:
                st.session_state[적용대기키] = 데이터
                st.rerun()

    if 도움말:
        st.caption(도움말)


def 불러온것_적용(적용대기키: str, 적용함수):
    """페이지 맨 위(위젯 만들기 전)에서 호출. 올린 설정을 실제로 반영합니다."""
    대기 = st.session_state.pop(적용대기키, None)
    if 대기 is not None:
        try:
            적용함수(대기)
            st.session_state[f"{적용대기키}_완료"] = True
        except Exception as e:  # noqa: BLE001
            st.session_state[f"{적용대기키}_오류"] = str(e)

    if st.session_state.pop(f"{적용대기키}_완료", False):
        st.success("설정을 불러왔습니다.", icon="📂")
    오류 = st.session_state.pop(f"{적용대기키}_오류", None)
    if 오류:
        st.error(f"불러오기 실패: {오류}")
