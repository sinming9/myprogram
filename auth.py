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
모듈버전 = "2026-07-31"


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


def _버전_점검():
    """이미 불러온 공용 모듈들이 모두 같은 버전인지 확인합니다.

    Streamlit 은 pages/ 의 화면 파일은 매번 디스크에서 다시 읽지만,
    storage.py 같은 공용 모듈은 서버를 처음 켤 때 읽은 것을 계속 씁니다.
    그래서 서버를 켜둔 채로 파일만 새로 받으면 화면 파일은 새 코드,
    공용 모듈은 옛 코드가 되어 AttributeError 가 납니다.
    그 상황을 알아보기 쉬운 안내로 바꿔줍니다.
    """
    낡은것 = []
    for 이름 in ("storage", "ui", "app_kit", "addons", "importer"):
        모듈 = sys.modules.get(이름)
        if 모듈 is None:
            continue
        if getattr(모듈, "모듈버전", None) != 모듈버전:
            낡은것.append(f"{이름}.py")
    return 낡은것


def _낡은모듈_안내(낡은것):
    st.error("서버를 껐다 켜야 합니다", icon="🔄")
    st.markdown(
        f"""
프로그램 파일은 새로 받으셨는데, **서버가 예전 코드를 들고 있습니다.**

Streamlit 은 화면 파일(`pages/`)만 매번 다시 읽고,
`storage.py` 같은 공용 파일은 **서버를 처음 켤 때 읽은 것**을 계속 씁니다.
그래서 서버를 켜둔 채로 파일만 바꾸면 둘이 어긋납니다.

옛 코드로 남아 있는 파일: **{', '.join(낡은것)}**

##### 해결 방법
1. 검은 콘솔 창을 **전부** 닫으세요 (여러 개 떠 있을 수 있습니다)
2. 안 닫히면 명령 프롬프트에서 `taskkill /f /im python.exe`
3. `실행_윈도우.bat` 을 다시 실행하세요

브라우저 새로고침(F5)만으로는 해결되지 않습니다. 서버를 껐다 켜야 합니다.

##### 그래도 같은 화면이 나오면
파일이 일부만 새로 받아진 것입니다. 압축을 풀 때 **모든 파일 덮어쓰기**를
선택해서 다시 풀어주세요. 공용 파일(`storage.py` · `ui.py` · `auth.py` ·
`app_kit.py` · `addons.py` · `importer.py`)은 항상 **한 세트로** 교체해야 합니다.
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
