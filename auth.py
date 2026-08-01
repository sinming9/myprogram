"""
==========================================================================
로그인/인증 공통 모듈  (v2 - 인터넷 공개 대응)
==========================================================================
모든 페이지 맨 위에서 require_login() 을 호출해서 인증 여부를 확인합니다.
한 번 로그인하면 그 브라우저 세션 전체(다른 페이지 포함)에 적용됩니다.

[비밀번호 설정 방법 - 반드시 확인하세요]
1. 이 파일이 있는 폴더에 ".streamlit/secrets.toml" 파일을 만드세요.
2. 그 안에 아래처럼 적으세요:
       password = "여기에_원하는_비밀번호"
3. secrets.toml 은 절대 공유하거나 git 에 올리지 마세요. (.gitignore 에 이미 포함)

[인터넷에 공개할 때 추가된 보호장치]  - 사용법은 그대로입니다
  · 비밀번호 비교를 hmac.compare_digest 로 처리 (타이밍 공격 방어)
  · 비밀번호를 평문 대신 해시로 저장 가능 (password_sha256 = "...")
  · 연속 실패 시 잠금 (기본 10회 실패 → 5분 잠금, 서버 전체 기준)
  · 오래 열어둔 세션 자동 만료 (기본 12시간)
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-08-02"


import hashlib
import hmac
import sys
import time

import streamlit as st

기본_비밀번호 = "changeme123"      # secrets.toml 이 없을 때만 쓰이는 임시 비밀번호
최대_실패횟수 = 10
잠금_초 = 300                       # 5분
세션_유효시간_초 = 12 * 60 * 60     # 12시간

# 모듈 전역 → 같은 서버 프로세스의 모든 접속자에게 공통 적용 (무작위 대입 방어)
_실패기록 = {"count": 0, "locked_until": 0.0}


def _설정값(키, 기본=None):
    try:
        return st.secrets[키]
    except Exception:
        return 기본


def _비밀번호_확인(입력: str) -> bool:
    해시 = _설정값("password_sha256")
    if 해시:
        계산 = hashlib.sha256(입력.encode("utf-8")).hexdigest()
        return hmac.compare_digest(계산.lower(), str(해시).strip().lower())
    정답 = str(_설정값("password", 기본_비밀번호))
    return hmac.compare_digest(입력, 정답)


def _기본비밀번호_사용중() -> bool:
    return (not _설정값("password_sha256")
            and str(_설정값("password", 기본_비밀번호)) == 기본_비밀번호)


def _세션_유효한가() -> bool:
    if not st.session_state.get("_인증됨", False):
        return False
    로그인시각 = st.session_state.get("_로그인시각", 0)
    if time.time() - 로그인시각 > 세션_유효시간_초:
        st.session_state["_인증됨"] = False
        st.session_state["_세션만료"] = True
        return False
    return True


# 공용 모듈이 반드시 갖고 있어야 하는 함수들.
#  ※ 버전 문자열만 비교하면, 같은 날 두 번 고쳤을 때(버전은 그대로인데
#    함수가 추가된 경우) 낡은 파일을 잡아내지 못합니다.
#    그래서 "필요한 함수가 실제로 있는지"를 함께 확인합니다.
필요기능 = {
    "ui": ["모바일_스타일", "테마_안내", "페이지_메뉴", "카드_줄", "원"],
    "storage": ["불러오기", "저장하기", "저장소_사이드바", "백업_사이드바",
               "임시서버_안내"],
    "app_kit": ["시작", "날짜로", "숫자로", "표만들기"],
    "addons": ["전체_불러오기", "정상_목록"],
    "importer": ["파일_읽기", "요약"],
}


def _버전_점검():
    """이미 불러온 공용 모듈이 최신인지 확인합니다. 문제가 있으면 목록 반환.

    두 가지를 봅니다.
      1) 모듈버전 문자열이 auth.py 와 같은가
      2) 그 모듈이 가지고 있어야 할 함수가 실제로 있는가

    이런 어긋남은 두 경우에 생깁니다.
      · 서버를 켜둔 채 파일만 새로 받았을 때
        (Streamlit 은 pages/ 는 매번 다시 읽지만 공용 모듈은 처음 것만 씁니다)
      · 파일을 일부만 올렸을 때 (pages/ 만 올리고 ui.py 는 안 올린 경우 등)
    """
    문제 = []
    for 이름, 함수들 in 필요기능.items():
        모듈 = sys.modules.get(이름)
        if 모듈 is None:
            continue
        빠진함수 = [f for f in 함수들 if not hasattr(모듈, f)]
        if 빠진함수:
            문제.append(f"{이름}.py (없는 기능: {', '.join(빠진함수)})")
        elif getattr(모듈, "모듈버전", None) != 모듈버전:
            문제.append(f"{이름}.py (버전 {getattr(모듈, '모듈버전', '표시없음')}"
                      f" ≠ {모듈버전})")
    return 문제


def _낡은모듈_안내(낡은것):
    st.error("파일 버전이 서로 맞지 않습니다", icon="🔄")
    st.markdown(
        f"""
화면 파일은 새 버전인데 **공용 파일이 옛 버전**입니다.

맞지 않는 파일: **{', '.join(낡은것)}**

##### 클라우드(Streamlit Cloud)에서 보고 있다면
파일을 **일부만** 올리신 것입니다.
GitHub 저장소에 위 파일들을 올리고 **Commit changes** 를 누르세요.
2~3분 뒤 자동으로 다시 배포됩니다.

##### 내 PC 에서 보고 있다면
서버가 예전 코드를 메모리에 들고 있습니다.
Streamlit 은 화면 파일(`pages/`)만 매번 다시 읽고, 공용 파일은
**서버를 처음 켤 때 읽은 것**을 계속 쓰기 때문입니다.

1. 검은 콘솔 창을 **전부** 닫으세요
2. 안 닫히면 명령 프롬프트에서 `taskkill /f /im python.exe`
3. `실행_윈도우.bat` 을 다시 실행하세요

브라우저 새로고침(F5)만으로는 해결되지 않습니다.

##### 공용 파일은 항상 한 세트로
`ui.py` · `storage.py` · `auth.py` · `app_kit.py` · `addons.py` · `importer.py`
이 여섯 개는 서로 맞물려 있으니 **함께** 교체하세요.
"""
    )
    st.stop()


def require_login(page_title: str = "개인 대시보드", page_icon: str = "🗂️",
                  layout: str = "centered"):
    """페이지 최상단에서 호출. 인증 안 되어 있으면 로그인 화면을 띄우고 멈춥니다."""
    try:
        st.set_page_config(page_title=page_title, page_icon=page_icon, layout=layout,
                           initial_sidebar_state="auto")
    except Exception:
        pass  # 이미 설정된 경우 무시

    낡은것 = _버전_점검()
    if 낡은것:
        _낡은모듈_안내(낡은것)

    if _세션_유효한가():
        return

    st.title("🔒 로그인")
    st.caption("개인 전용 대시보드입니다. 비밀번호를 입력하세요.")

    if st.session_state.pop("_세션만료", False):
        st.info("일정 시간이 지나 자동으로 로그아웃되었습니다. 다시 로그인해 주세요.", icon="⏱️")

    if _기본비밀번호_사용중():
        st.warning(
            "아직 기본 비밀번호(changeme123)를 쓰고 있어요. "
            "`.streamlit/secrets.toml` 파일을 만들어 본인만의 비밀번호로 바꿔주세요. "
            "특히 인터넷에 공개할 거라면 반드시 바꿔야 합니다.",
            icon="⚠️",
        )

    남은잠금 = _실패기록["locked_until"] - time.time()
    if 남은잠금 > 0:
        st.error(f"비밀번호를 여러 번 틀려서 잠겼습니다. {int(남은잠금) + 1}초 후 다시 시도하세요.")
        st.stop()

    with st.form("login_form"):
        pw = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("입장하기", use_container_width=True)

    if submitted:
        if pw and _비밀번호_확인(pw):
            _실패기록["count"] = 0
            _실패기록["locked_until"] = 0.0
            st.session_state["_인증됨"] = True
            st.session_state["_로그인시각"] = time.time()
            st.rerun()
        else:
            _실패기록["count"] += 1
            남은 = 최대_실패횟수 - _실패기록["count"]
            if 남은 <= 0:
                _실패기록["locked_until"] = time.time() + 잠금_초
                _실패기록["count"] = 0
                st.error(f"실패 횟수를 초과했습니다. {잠금_초 // 60}분간 잠깁니다.")
            else:
                time.sleep(0.7)   # 자동 대입 속도 늦추기
                st.error(f"비밀번호가 올바르지 않습니다. (남은 시도 {남은}회)")

    st.stop()


def 로그아웃_버튼():
    if st.sidebar.button("🚪 로그아웃", use_container_width=True):
        for 키 in ("_인증됨", "_로그인시각"):
            st.session_state.pop(키, None)
        st.rerun()


def 비밀번호_해시_만들기(평문: str) -> str:
    """secrets.toml 에 넣을 password_sha256 값을 만들어 줍니다 (도우미)."""
    return hashlib.sha256(평문.encode("utf-8")).hexdigest()
