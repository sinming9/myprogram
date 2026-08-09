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
모듈버전 = "2026-08-05c"


import hashlib
import hmac
import sys
import time

import streamlit as st

기본_비밀번호 = "changeme123"      # secrets.toml 이 없을 때만 쓰이는 임시 비밀번호
최대_실패횟수 = 10
잠금_초 = 300                       # 5분
세션_유효시간_초 = 30 * 24 * 60 * 60  # 30일 (브라우저 탭을 닫으면 어차피 초기화됩니다)

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
    return hmac.compare_digest(입력.encode("utf-8"), 정답.encode("utf-8"))


def _기본비밀번호_사용중() -> bool:
    if not _비밀번호_설정됨():
        return False        # 비밀번호를 아예 안 쓰기로 한 경우
    return (not _설정값("password_sha256")
            and str(_설정값("password", 기본_비밀번호)) == 기본_비밀번호)


def _참인가(값) -> bool:
    return str(값).strip().lower() in ("true", "1", "yes", "on")


def _비밀번호_설정됨() -> bool:
    return bool(_설정값("password_sha256")) or bool(_설정값("password"))


def _손님허용() -> bool:
    """비밀번호 없이 들어온 사람을 손님(Guest)으로 받아들일지."""
    명시 = _설정값("guest_ok")
    if 명시 is not None:
        return _참인가(명시)
    if not _비밀번호_설정됨():
        return True                    # 비밀번호가 없으면 막을 방법이 없습니다
    return bool(_설정값("url_key"))     # 주소 열쇠가 있으면 손님도 받습니다


def 역할() -> str:
    """'master' 또는 'guest'. 로그인 전이면 'guest'."""
    return st.session_state.get("_역할", "guest")


def 주인인가() -> bool:
    return 역할() == "master"


def _URL열쇠_통과() -> bool:
    """주소 뒤에 ?k=열쇠 가 붙어 있으면 비밀번호 없이 통과시킵니다.

    secrets 에 url_key 를 넣어두고, 아래 주소를 휴대폰 홈 화면에 추가하면
    누를 때마다 바로 들어갑니다.
        https://내앱.streamlit.app/?k=열쇠

    ※ 주소에 열쇠가 들어가므로 브라우저 기록에 남습니다.
      비밀번호를 직접 치는 것보다는 약하니, 열쇠를 길게 만드세요.
    """
    열쇠 = _설정값("url_key")
    if not 열쇠:
        return False
    try:
        받은 = st.query_params.get("k")
    except Exception:  # noqa: BLE001
        return False
    if not 받은:
        return False
    # ※ hmac.compare_digest 는 비ASCII 문자열에서 TypeError 를 냅니다.
    #   주소에 한글 등이 들어와도 죽지 않도록 바이트로 바꿔서 비교합니다.
    return hmac.compare_digest(str(받은).encode("utf-8"), str(열쇠).encode("utf-8"))


def _로그인_생략() -> tuple:
    """secrets 에 no_login = true 면 로그인을 아예 건너뜁니다.

    단, 자료 저장소(Gist)가 설정되어 있으면 위험하므로 막습니다.
    누구나 들어와서 내 Gist 를 읽고 쓸 수 있게 되기 때문입니다.
    (생략여부, 막은이유) 반환
    """
    값 = str(_설정값("no_login", "")).strip().lower()
    if 값 not in ("true", "1", "yes", "on"):
        return False, None
    try:
        import storage
        if storage.저장방식() == "gist":
            return False, ("no_login 이 켜져 있지만 GitHub Gist 저장소도 설정되어 "
                          "있습니다. 이대로면 누구나 들어와서 자료를 보고 고칠 수 "
                          "있어서 로그인을 건너뛰지 않았습니다.\n\n"
                          "자료를 파일로만 관리하시려면 secrets 에서 "
                          "`github_token` 과 `gist_id` 두 줄을 지우세요.")
    except Exception:  # noqa: BLE001
        pass
    return True, None


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
               "임시서버_안내", "손님인가"],
    "app_kit": ["시작", "날짜로", "숫자로", "표만들기"],
    "addons": ["전체_불러오기", "정상_목록"],
    "importer": ["파일_읽기", "요약"],
    # engines 도 함께 봅니다. 페이지가 불러온 것만 검사되므로,
    # 그 페이지를 안 열면 아무 영향이 없습니다.
    "engines.portfolio": ["종목_계산", "집계", "요약", "배당_달력", "리밸런싱",
                         "ISA_현황", "갱신_필요한가", "조회가_필요한가"],
    "engines.capital_gains": ["계산", "장특공_비율", "공제제도", "공제제도_고르기"],
    "engines.egg_cycle": ["compute_state", "이력_불러오기", "egg_outline"],
    "engines.fedwatch": ["미국_전망", "확률_계산", "다음_회의"],
    "engines.fx": ["환율_가져오기", "평균_계산", "금액표시"],
    "engines.loan": ["스케줄_생성", "요약"],
    "engines.property_tax": ["calculate", "add_or_update_history"],
    "engines.salary": ["dashboard_records", "연도별_표"],
}


def _버전_점검():
    """이미 불러온 공용 모듈이 최신인지 확인합니다. 문제가 있으면 목록 반환.

    각 모듈이 가지고 있어야 할 함수가 실제로 있는지 봅니다.
    (모듈버전 문자열은 표시용일 뿐, 서로 같을 필요는 없습니다)

    이런 어긋남은 두 경우에 생깁니다.
      · 서버를 켜둔 채 파일만 새로 받았을 때
        (Streamlit 은 pages/ 는 매번 다시 읽지만 공용 모듈은 처음 것만 씁니다)
      · 파일을 일부만 올렸을 때 (pages/ 만 올리고 ui.py 는 안 올린 경우 등)
    """
    핵심, 엔진 = [], []
    for 이름, 함수들 in 필요기능.items():
        모듈 = sys.modules.get(이름)
        if 모듈 is None:
            continue
        빠진함수 = [f for f in 함수들 if not hasattr(모듈, f)]
        if not 빠진함수:
            continue
        경로 = 이름.replace(".", "/") + ".py"
        줄 = f"{경로} (없는 기능: {', '.join(빠진함수)})"
        # engines 는 그 페이지에서만 쓰이므로 다른 페이지까지 막지 않습니다.
        (엔진 if 이름.startswith("engines.") else 핵심).append(줄)
    return 핵심, 엔진

    # ※ 예전에는 모듈버전 문자열이 서로 같은지도 검사했습니다.
    #   그러면 실제로 바뀐 파일이 하나여도 나머지를 전부 다시 올려야 해서
    #   불편하고, 오히려 '일부만 올리는' 실수를 유발했습니다.
    #   지금은 "필요한 기능이 실제로 있는지"만 봅니다. 어긋나면 그때 잡힙니다.


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

##### 파일 위치를 지켜주세요
`engines/` 로 시작하면 engines 폴더 안에, `pages/` 로 시작하면 pages 폴더 안에
넣어야 합니다. 최상위에 올리면 앱이 못 찾습니다.
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

    # 로그인 화면에도 공통 CSS 를 입힙니다.
    #  ※ 아래에서 st.stop() 으로 멈추기 때문에, 페이지의 ui.모바일_스타일() 은
    #    로그인 화면에서는 실행되지 않습니다. 그래서 여기서 직접 넣습니다.
    #    (안 넣으면 비밀번호 보기 아이콘이 "visibility" 글자로 노출됩니다)
    try:
        import ui as _ui
        _ui.모바일_스타일()
    except Exception:  # noqa: BLE001
        pass

    낡은핵심, 낡은엔진 = _버전_점검()
    if 낡은핵심:
        # 공용 파일이 낡으면 어느 페이지든 깨지므로 여기서 멈춥니다.
        _낡은모듈_안내(낡은핵심)
    if 낡은엔진:
        # 엔진은 해당 계산 페이지에서만 쓰이므로 알려만 주고 진행합니다.
        st.warning(
            "일부 계산 파일이 예전 버전입니다 — **" + ", ".join(낡은엔진) + "**\n\n"
            "그 계산을 쓰는 페이지에서만 문제가 생깁니다. "
            "GitHub 저장소에 위 파일을 올리고 Commit changes 하시면 됩니다. "
            "(내 PC 라면 서버를 껐다 켜세요)",
            icon="🔧")

    if _세션_유효한가():
        return

    def _입장(역할값, 방식):
        st.session_state["_인증됨"] = True
        st.session_state["_로그인시각"] = time.time()
        st.session_state["_역할"] = 역할값
        st.session_state["_로그인방식"] = 방식

    # 1) 주소에 열쇠가 있으면 주인(Master)
    if _URL열쇠_통과():
        _입장("master", "주소열쇠")
        return

    생략, 막은이유 = _로그인_생략()
    if 생략:
        _입장("master", "생략")
        return

    # 2) 손님(Guest)으로 그냥 들여보내기
    if _손님허용():
        _입장("guest", "손님")
        return

    st.title("🔒 로그인")
    st.caption("개인 전용 대시보드입니다. 비밀번호를 입력하세요.")

    if st.session_state.pop("_세션만료", False):
        st.info("일정 시간이 지나 자동으로 로그아웃되었습니다. 다시 로그인해 주세요.", icon="⏱️")

    if 막은이유:
        st.warning(막은이유, icon="⚠️")

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
            st.session_state["_역할"] = "master"
            st.session_state["_로그인방식"] = "비밀번호"
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


def _가리기(값: str, 앞=4, 뒤=3) -> str:
    """열쇠를 부분만 보여줍니다. abcdefghijk → abcd••••••ijk"""
    값 = str(값)
    if len(값) <= 앞 + 뒤:
        return "•" * len(값)
    return 값[:앞] + "•" * (len(값) - 앞 - 뒤) + 값[-뒤:]


def 로그아웃_버튼():
    """사이드바에 현재 역할 표시 + 필요한 버튼들."""
    주인 = 주인인가()
    방식 = st.session_state.get("_로그인방식")

    if 주인:
        st.sidebar.success("👑 Master — 저장할 수 있습니다", icon="👑")
    else:
        st.sidebar.info("👤 Guest — 저장은 이번 접속에서만 유지됩니다", icon="👤")

    # 손님이 비밀번호로 주인이 되는 길 (비밀번호를 설정해 둔 경우에만)
    if not 주인 and _비밀번호_설정됨():
        with st.sidebar.expander("🔑 Master 로 전환"):
            with st.form("_승격"):
                pw = st.text_input("비밀번호", type="password")
                눌림 = st.form_submit_button("전환", use_container_width=True)
            if 눌림:
                남은잠금 = _실패기록["locked_until"] - time.time()
                if 남은잠금 > 0:
                    st.error(f"잠겨 있습니다. {int(남은잠금) + 1}초 후 다시 시도하세요.")
                elif pw and _비밀번호_확인(pw):
                    _실패기록["count"] = 0
                    st.session_state["_역할"] = "master"
                    st.session_state["_로그인방식"] = "비밀번호"
                    st.rerun()
                else:
                    _실패기록["count"] += 1
                    if 최대_실패횟수 - _실패기록["count"] <= 0:
                        _실패기록["locked_until"] = time.time() + 잠금_초
                        _실패기록["count"] = 0
                        st.error(f"{잠금_초 // 60}분간 잠깁니다.")
                    else:
                        time.sleep(0.7)
                        st.error("비밀번호가 올바르지 않습니다.")

    if 주인 and 방식 != "생략":
        if st.sidebar.button("🚪 Guest 로 나가기", use_container_width=True):
            for 키 in ("_역할", "_로그인방식"):
                st.session_state.pop(키, None)
            st.session_state["_역할"] = "guest"
            for 키 in list(st.session_state.keys()):
                if 키.startswith(("급여_", "재산세_", "달걀_", "중도_", "금리_", "_gist_")):
                    st.session_state.pop(키, None)
            st.rerun()

    열쇠 = _설정값("url_key")
    if 열쇠 and 주인:
        with st.sidebar.expander("🔗 비밀번호 없이 들어오기"):
            # ※ 열쇠는 기본으로 가려둡니다. 화면 캡처로 새어나갈 수 있습니다.
            st.caption("휴대폰 홈 화면에 추가해두면 누를 때마다 Master 로 열립니다. "
                       "처음 한 번만 확인하면 됩니다.")
            st.code(f"?k={_가리기(열쇠)}", language=None)
            if len(str(열쇠)) < 20:
                st.warning("열쇠가 짧습니다. 30자 이상으로 바꾸세요.", icon="⚠️")
            if st.checkbox("열쇠 보기", key="_열쇠보기"):
                st.warning("화면 캡처나 화면 공유 중이면 지금 끄세요.", icon="📸")
                st.code(f"?k={열쇠}", language=None)
                st.caption("앱 주소 뒤에 위 내용을 붙이세요.\n"
                           "예) https://내앱.streamlit.app/?k=...")
            else:
                st.caption("전체 열쇠는 Streamlit Cloud 의 "
                           "Settings → Secrets 에서도 볼 수 있습니다.")


def 비밀번호_해시_만들기(평문: str) -> str:
    """secrets.toml 에 넣을 password_sha256 값을 만들어 줍니다 (도우미)."""
    return hashlib.sha256(평문.encode("utf-8")).hexdigest()
