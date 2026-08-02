"""
==========================================================================
데이터 저장/불러오기 공통 모듈  (v3 - GitHub 비공개 Gist 지원)
==========================================================================
저장 방식이 두 가지입니다. 설정에 따라 자동으로 골라집니다.

  [로컬 파일]  기본. 앱 폴더의 data/ 안에 JSON 으로 저장.
               내 PC 에서 실행할 때 쓰입니다.

  [Gist]       secrets 에 github_token 과 gist_id 가 있으면 이 방식.
               GitHub 의 비공개(secret) Gist 하나에 모든 파일을 넣습니다.
               Streamlit Cloud 처럼 서버가 재시작되면 파일이 사라지는
               환경에서도 자료가 그대로 남습니다.

Gist 를 쓸 때도 로컬 파일에 사본을 남깁니다.
인터넷이 잠깐 안 되거나 GitHub 이 응답하지 않을 때 그 사본으로 버팁니다.

------------------------------------------------------------------
Gist 설정 방법 (5분)
------------------------------------------------------------------
1) 토큰 만들기
   GitHub → 우측 상단 프로필 → Settings → Developer settings
   → Personal access tokens → Tokens (classic) → Generate new token (classic)
   - Note: 아무 이름 (예: dashboard)
   - Expiration: No expiration 또는 원하는 기간
   - Select scopes: gist 하나만 체크
   - 생성 후 나오는 ghp_... 문자열을 복사 (다시 볼 수 없으니 바로 저장)

2) Gist 만들기
   https://gist.github.com 접속 → 아무 파일 하나 만들기
   - Filename: dashboard.txt
   - 내용: 아무거나 (예: hello)
   - "Create secret gist" 버튼으로 생성 (Public 아님!)
   - 주소창의 마지막 부분이 gist_id 입니다.
     https://gist.github.com/사용자명/[여기가_gist_id]

3) 앱에 알려주기
   내 PC          : .streamlit/secrets.toml 파일에 아래 두 줄 추가
   Streamlit Cloud: 앱 → Settings → Secrets 에 아래 두 줄 붙여넣기

       github_token = "ghp_여기에_복사한_토큰"
       gist_id = "여기에_gist_id"

   ※ 토큰은 절대 GitHub 저장소에 커밋하지 마세요.
     secrets.toml 은 .gitignore 에 이미 들어 있습니다.
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시. 모든 공용 모듈이 같아야 합니다.
모듈버전 = "2026-08-02g"


import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date

import streamlit as st

앱_폴더 = os.path.dirname(os.path.abspath(__file__))
데이터_폴더 = os.path.join(앱_폴더, "data")

GIST_API = "https://api.github.com/gists"
캐시_유효초 = 300          # 5분 지나면 Gist 를 다시 읽어옵니다
_캐시키 = "_gist_캐시"
_캐시시각키 = "_gist_캐시시각"

# 기본 프로그램들의 파일 이름. 여기 없는 키는 자동으로 "키이름.json" 이 됩니다.
파일 = {
    "loan": "loan_settings.json",
    "property_tax": "property_tax.json",
    "salary": "salary_data.json",
}

_안전한_글자 = re.compile(r"[^0-9A-Za-z가-힣_\-]")


def 파일이름(키: str) -> str:
    """저장 키를 안전한 파일 이름으로 바꿉니다 (경로 조작 방지)."""
    if 키 in 파일:
        return 파일[키]
    정리 = _안전한_글자.sub("_", str(키)).strip("._-")
    if not 정리:
        정리 = "data"
    return f"{정리[:60]}.json"


def JSON문자열(값) -> str:
    return json.dumps(값, ensure_ascii=False, indent=2, default=str)


# ==========================================================================
# 설정 읽기
# ==========================================================================

def _설정(키, 기본=None):
    try:
        값 = st.secrets[키]
        return str(값).strip() if 값 is not None else 기본
    except Exception:  # noqa: BLE001
        return os.environ.get(키.upper(), 기본)


def Gist_설정():
    """(토큰, gist_id) 반환. 하나라도 없으면 (None, None)."""
    토큰 = _설정("github_token")
    아이디 = _설정("gist_id")
    if 토큰 and 아이디:
        return 토큰, 아이디
    return None, None


def 저장방식() -> str:
    return "gist" if Gist_설정()[0] else "local"


def 임시서버인가() -> bool:
    """Streamlit Community Cloud 등 재시작 시 파일이 사라지는 환경인지 추정."""
    if os.environ.get("HOSTNAME", "").startswith("streamlit"):
        return True
    if os.path.abspath(앱_폴더).startswith("/mount/src"):
        return True
    return False


# ==========================================================================
# GitHub Gist 통신
# ==========================================================================

def _요청(url, 토큰, 방식="GET", 본문=None, 시간제한=15):
    데이터 = json.dumps(본문).encode("utf-8") if 본문 is not None else None
    req = urllib.request.Request(url, data=데이터, method=방식)
    req.add_header("Authorization", f"Bearer {토큰}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "personal-dashboard")
    if 데이터 is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _오류설명(e) -> str:
    if isinstance(e, urllib.error.HTTPError):
        안내 = {
            401: "토큰이 잘못되었거나 만료되었습니다. github_token 을 다시 확인하세요.",
            403: "권한이 없습니다. 토큰에 gist 권한이 있는지 확인하세요.",
            404: "Gist 를 찾을 수 없습니다. gist_id 가 맞는지, "
                 "그 Gist 가 토큰 주인의 것인지 확인하세요.",
        }.get(e.code, "")
        return f"GitHub 응답 {e.code}. {안내}".strip()
    if isinstance(e, urllib.error.URLError):
        return f"GitHub 에 연결하지 못했습니다 ({e.reason}). 인터넷 연결을 확인하세요."
    return f"{type(e).__name__}: {e}"


def _gist_전체읽기(강제=False):
    """Gist 의 모든 파일을 {파일이름: 문자열} 로 읽어옵니다. 실패하면 None."""
    토큰, 아이디 = Gist_설정()
    if not 토큰:
        return None

    이전 = st.session_state.get(_캐시키)
    시각 = st.session_state.get(_캐시시각키, 0)
    if 이전 is not None and not 강제 and (time.time() - 시각) < 캐시_유효초:
        return 이전

    try:
        결과 = _요청(f"{GIST_API}/{아이디}", 토큰)
    except Exception as e:  # noqa: BLE001
        st.session_state["_gist_오류"] = _오류설명(e)
        return 이전          # 캐시가 있으면 그거라도 씀

    파일들 = {}
    for 이름, 정보 in (결과.get("files") or {}).items():
        내용 = 정보.get("content")
        if 정보.get("truncated") and 정보.get("raw_url"):
            try:
                with urllib.request.urlopen(정보["raw_url"], timeout=15) as r:
                    내용 = r.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                pass
        파일들[이름] = 내용 or ""

    st.session_state[_캐시키] = 파일들
    st.session_state[_캐시시각키] = time.time()
    st.session_state.pop("_gist_오류", None)
    return 파일들


def _gist_쓰기(이름, 문자열):
    """(성공, 메시지)"""
    토큰, 아이디 = Gist_설정()
    if not 토큰:
        return False, "Gist 설정이 없습니다."
    try:
        _요청(f"{GIST_API}/{아이디}", 토큰, "PATCH",
             {"files": {이름: {"content": 문자열}}})
    except Exception as e:  # noqa: BLE001
        return False, _오류설명(e)

    캐시 = st.session_state.get(_캐시키)
    if 캐시 is None:
        캐시 = {}
    캐시[이름] = 문자열
    st.session_state[_캐시키] = 캐시
    st.session_state[_캐시시각키] = time.time()
    return True, "GitHub Gist 에 저장했습니다."


def 새로고침():
    """다른 기기에서 바꾼 내용을 다시 읽어옵니다."""
    st.session_state.pop(_캐시키, None)
    st.session_state.pop(_캐시시각키, None)
    _gist_전체읽기(강제=True)


# ==========================================================================
# 로컬 파일
# ==========================================================================

def _경로(키: str) -> str:
    os.makedirs(데이터_폴더, exist_ok=True)
    return os.path.join(데이터_폴더, 파일이름(키))


def _로컬_읽기(키, 기본값):
    try:
        with open(_경로(키), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 기본값


def _로컬_쓰기(키, 값):
    try:
        with open(_경로(키), "w", encoding="utf-8") as f:
            f.write(JSON문자열(값))
        return True, None
    except OSError as e:
        return False, str(e)


# ==========================================================================
# 바깥에서 쓰는 함수 (페이지들은 이 두 개만 씁니다)
# ==========================================================================

def 손님인가() -> bool:
    """Master 가 아니면 손님. auth 를 못 읽으면 안전하게 손님으로 봅니다."""
    try:
        import auth
        return not auth.주인인가()
    except Exception:  # noqa: BLE001
        return True


_손님키 = "_손님자료"


def 불러오기(키: str, 기본값):
    """저장된 자료를 읽어옵니다. 없거나 깨져 있으면 기본값.

    ★ 손님(Guest)은 저장소를 읽지 않습니다.
      저장만 막고 읽기를 열어두면, 주소만 아는 사람이 연봉·재산세 자료를
      그대로 볼 수 있게 됩니다. 손님에게는 이번 접속에서 직접 넣은 값만
      돌려줍니다.
    """
    if 손님인가():
        return st.session_state.get(_손님키, {}).get(키, 기본값)

    if 저장방식() == "gist":
        파일들 = _gist_전체읽기()
        if 파일들 is not None:
            내용 = 파일들.get(파일이름(키))
            if 내용:
                try:
                    return json.loads(내용)
                except json.JSONDecodeError:
                    pass
            # Gist 에 그 파일이 아직 없으면 아래에서 로컬 사본을 확인합니다
    return _로컬_읽기(키, 기본값)


def 저장하기(키: str, 값) -> tuple:
    """(성공여부, 메시지) 반환"""
    if 손님인가():
        # 손님은 서버에 남기지 않고 이번 접속(브라우저 탭) 안에서만 유지합니다.
        보관 = st.session_state.setdefault(_손님키, {})
        보관[키] = 값
        return True, ("👤 Guest 모드입니다. 이번 접속 동안만 유지되고 "
                     "서버에는 저장되지 않습니다. 창을 닫으면 사라집니다.\n\n"
                     "계속 보관하려면 사이드바에서 Master 로 전환하거나, "
                     "백업 / 복원에서 파일로 내려받으세요.")

    문자열 = JSON문자열(값)
    로컬성공, 로컬오류 = _로컬_쓰기(키, 값)

    if 저장방식() == "gist":
        성공, 메시지 = _gist_쓰기(파일이름(키), 문자열)
        if 성공:
            return True, "저장했습니다. (GitHub Gist — 서버가 재시작돼도 남아 있습니다)"
        if 로컬성공:
            return False, (f"Gist 저장에 실패했습니다: {메시지}  "
                          "임시로 서버 안에만 저장해 두었습니다. "
                          "사이드바의 백업 / 복원에서 파일로 내려받아 두세요.")
        return False, f"저장 실패: {메시지}"

    if not 로컬성공:
        return False, f"저장 실패: {로컬오류}"
    if 임시서버인가():
        return True, ("저장했습니다. 다만 이 서버는 재시작 시 파일이 사라집니다. "
                     "GitHub Gist 를 설정하거나 백업 파일을 내려받아 두세요.")
    return True, f"저장했습니다. 다음에 열 때 자동으로 불러옵니다. ({_경로(키)})"


# ==========================================================================
# 화면 표시
# ==========================================================================

def 저장소_상태():
    """(아이콘, 짧은설명, 자세한설명)"""
    if 손님인가():
        return "👤", "저장 안 됨 (Guest)", ("이번 접속에서만 자료가 유지됩니다. "
                                       "창을 닫으면 사라집니다. 사이드바에서 "
                                       "Master 로 전환하면 저장됩니다.")
    if 저장방식() == "gist":
        오류 = st.session_state.get("_gist_오류")
        if 오류:
            return "⚠️", "Gist 연결 문제", 오류
        _, 아이디 = Gist_설정()
        return "☁️", "GitHub Gist", f"비공개 Gist `{아이디[:8]}…` 에 저장 중입니다."
    if 임시서버인가():
        return "⚠️", "임시 저장", ("클라우드 서버 안에만 저장됩니다. 재시작하면 사라집니다. "
                              "GitHub Gist 설정을 권합니다.")
    return "💾", "내 PC", f"`{데이터_폴더}` 에 저장 중입니다."


def 저장소_사이드바():
    """사이드바에 현재 저장 위치와 새로고침 버튼을 표시합니다."""
    아이콘, 짧게, 자세히 = 저장소_상태()
    with st.sidebar.expander(f"{아이콘} 저장 위치: {짧게}", expanded=False):
        st.caption(자세히)
        if 저장방식() == "gist":
            if st.button("🔄 다른 기기의 변경 내용 가져오기", width="stretch",
                         key="_gist_새로고침"):
                새로고침()
                for 키 in ("급여_자료", "재산세_자료", "_대출_자동로드"):
                    st.session_state.pop(키, None)
                st.rerun()
            st.caption("여러 기기에서 번갈아 쓸 때, 다른 기기에서 저장한 내용을 "
                       "바로 보려면 이 버튼을 누르세요.")
        else:
            st.caption("휴대폰에서도 자료를 유지하려면 GitHub Gist 설정이 필요합니다. "
                       "`외부접속_설정_가이드.md` 를 보세요.")


def 임시서버_안내():
    """저장 관련 주의사항을 화면 위쪽에 띄웁니다."""
    if 손님인가():
        st.info(
            "👤 **Guest 모드** — 계산기는 모두 쓸 수 있지만, 입력한 값은 "
            "이번 접속에서만 유지되고 저장되지 않습니다. "
            "예전에 저장해 둔 자료도 불러오지 않습니다.",
            icon="👤",
        )
        return
    if 임시서버인가() and 저장방식() != "gist":
        st.warning(
            "클라우드에서 실행 중인데 저장소 설정이 없습니다. "
            "입력한 자료는 서버가 재시작되면 사라집니다. "
            "`외부접속_설정_가이드.md` 의 GitHub Gist 설정을 따라 하시거나, "
            "왼쪽 백업 / 복원에서 파일로 내려받아 두세요.",
            icon="☁️",
        )
    오류 = st.session_state.get("_gist_오류")
    if 오류:
        st.warning(f"GitHub Gist 를 읽지 못했습니다. {오류}", icon="⚠️")


def 백업_사이드바(키: str, 현재값, 파일이름_접두: str, 복원_콜백=None):
    """사이드바에 백업 내려받기 / 복원 UI 를 그립니다."""
    with st.sidebar.expander("💾 백업 / 복원", expanded=False):
        st.download_button(
            "⬇️ 백업 파일 내려받기",
            data=JSON문자열(현재값).encode("utf-8"),
            file_name=f"{파일이름_접두}_{date.today().isoformat()}.json",
            mime="application/json",
            width="stretch",
        )
        올린파일 = st.file_uploader("⬆️ 백업 파일 복원", type=["json"], key=f"restore_{키}")
        if 올린파일 is not None and st.button("이 파일로 되돌리기", key=f"restore_btn_{키}",
                                          width="stretch"):
            try:
                데이터 = json.load(올린파일)
            except json.JSONDecodeError as e:
                st.error(f"파일을 읽을 수 없습니다: {e}")
                return
            저장하기(키, 데이터)
            if 복원_콜백:
                복원_콜백(데이터)
            st.success("복원했습니다.")
            st.rerun()
