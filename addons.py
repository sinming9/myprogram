"""
==========================================================================
addons - myapps/ 폴더에 넣은 내 프로그램들을 자동으로 찾아주는 모듈
==========================================================================
myapps/ 폴더에 .py 파일을 하나 넣으면 대시보드에 자동으로 나타납니다.
파일 이름은 자유롭게 지으면 됩니다 (번호나 이모지 안 붙여도 됨).

파일 안에 아래 네 가지만 준비하면 됩니다.

    제목  = "적금 만기 계산기"     # 없으면 파일 이름을 씁니다
    아이콘 = "🐷"                  # 없으면 🧩
    설명  = "한 줄 설명"           # 없어도 됨

    def 실행():                    # ← 이 함수가 화면을 그립니다 (필수)
        import streamlit as st
        st.write("안녕")

파일 이름이 _ 또는 . 로 시작하면 무시됩니다 (임시 파일용).
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-08-02c"


import importlib
import os
import sys
import traceback

앱_폴더 = os.path.dirname(os.path.abspath(__file__))
애드온_폴더 = os.path.join(앱_폴더, "myapps")

if 앱_폴더 not in sys.path:
    sys.path.insert(0, 앱_폴더)


def 파일이름_목록():
    """myapps/ 안의 쓸 수 있는 모듈 이름들 (확장자 없이, 이름순)"""
    if not os.path.isdir(애드온_폴더):
        return []
    이름들 = []
    for 파일 in sorted(os.listdir(애드온_폴더)):
        if not 파일.endswith(".py"):
            continue
        if 파일.startswith(("_", ".")):
            continue
        이름들.append(파일[:-3])
    return 이름들


def _정보_뽑기(모듈, 이름):
    실행함수 = getattr(모듈, "실행", None)
    return {
        "이름": 이름,
        "제목": str(getattr(모듈, "제목", None) or 이름.replace("_", " ")),
        "아이콘": str(getattr(모듈, "아이콘", None) or "🧩"),
        "설명": str(getattr(모듈, "설명", None) or ""),
        "실행": 실행함수 if callable(실행함수) else None,
        "모듈": 모듈,
    }


def 하나_불러오기(이름, 새로고침=False):
    """(정보dict, 오류문자열) 반환. 성공하면 오류는 None."""
    모듈명 = f"myapps.{이름}"
    try:
        if 모듈명 in sys.modules:
            모듈 = (importlib.reload(sys.modules[모듈명]) if 새로고침
                  else sys.modules[모듈명])
        else:
            모듈 = importlib.import_module(모듈명)
    except Exception:  # noqa: BLE001
        return None, traceback.format_exc()

    정보 = _정보_뽑기(모듈, 이름)
    if 정보["실행"] is None:
        return 정보, (f"'{이름}.py' 안에 실행() 함수가 없습니다.\n"
                    f"파일에 아래처럼 함수를 하나 만들어 주세요.\n\n"
                    f"    def 실행():\n"
                    f"        import streamlit as st\n"
                    f"        st.write('안녕')\n")
    return 정보, None


def 전체_불러오기(새로고침=False):
    """[(정보dict 또는 None, 오류문자열 또는 None, 이름), ...]"""
    결과 = []
    for 이름 in 파일이름_목록():
        정보, 오류 = 하나_불러오기(이름, 새로고침)
        결과.append((정보, 오류, 이름))
    return 결과


def 정상_목록(새로고침=False):
    """실행 가능한 애드온만 (Home 화면 목록용). 실패한 건 조용히 제외."""
    출력 = []
    for 정보, 오류, _이름 in 전체_불러오기(새로고침):
        if 정보 and 오류 is None:
            출력.append(정보)
    return 출력
