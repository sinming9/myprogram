"""
==========================================================================
카카오톡 "나에게 보내기" 엔진
==========================================================================
[무엇을 하나]
  카카오톡의 **나와의 채팅방**으로 글을 보냅니다.

[왜 '나에게 보내기' 인가]
  카카오는 메시지를 보내는 길이 두 가지입니다.

    나에게 보내기 (이 파일)   사업자등록 불필요 · 심사 불필요 · 무료
    알림톡 / 친구톡           사업자등록 필요 · 심사 필요 · 건당 과금

  개인이 쓸 수 있는 건 앞의 것뿐입니다. 대신 나에게만 보낼 수 있는데,
  가격 알림은 내가 받는 것이니 그걸로 충분합니다.

--------------------------------------------------------------------------
★ 이 파일에서 가장 중요한 것 — 토큰이 6시간마다 만료됩니다
--------------------------------------------------------------------------
  텔레그램 봇 토큰은 한 번 받으면 영구입니다. 카카오는 다릅니다.

    액세스 토큰   6시간   → 보낼 때마다 새로 발급받아야 함
    리프레시 토큰 2개월   → 액세스 토큰을 발급받는 데 쓰는 열쇠

  리프레시 토큰은 갱신할 때 카카오가 알아서 연장해 줍니다. 단
  **남은 기간이 1개월 미만일 때만** 새 리프레시 토큰을 함께 내려줍니다.
  그래서 새 것이 왔을 때는 **반드시 저장해야** 합니다. 안 하면 2개월 뒤
  조용히 죽고, 브라우저 로그인을 처음부터 다시 해야 합니다.

  이 파일은 저장을 직접 하지 않습니다. `토큰_갱신()` 이 새 리프레시 토큰을
  돌려주므로, 부르는 쪽(페이지 / scripts/hotel_check.py)이 Gist 에 넣습니다.

--------------------------------------------------------------------------
처음 한 번만 하는 일 (브라우저가 필요합니다)
--------------------------------------------------------------------------
  1) developers.kakao.com → 애플리케이션 추가
  2) 앱 설정 → 플랫폼 → Web 플랫폼 등록 → 사이트 도메인에
     `https://localhost` 를 넣습니다
  3) 카카오 로그인 → 활성화 ON, Redirect URI 에 `https://localhost` 등록
  4) 카카오 로그인 → 동의항목 → **카카오톡 메시지 전송(talk_message)** 을
     '이용 중 동의' 로 설정
  5) 인증주소() 가 만들어 주는 주소를 브라우저에서 엽니다
  6) 로그인·동의하면 주소창이 `https://localhost/?code=XXXX` 로 바뀝니다
     (페이지는 안 열립니다. 정상입니다 — 주소창의 code 만 필요합니다)
  7) 그 code 를 토큰_받기() 에 넣으면 리프레시 토큰이 나옵니다

  ※ 이 파일은 streamlit 을 쓰지 않습니다. GitHub Actions 에서도 그대로
    돌아야 하기 때문입니다.
==========================================================================
"""

# 이 파일이 최신인지 확인하는 표시.
모듈버전 = "2026-09-08"


import json
import urllib.error
import urllib.parse
import urllib.request

인증_주소 = "https://kauth.kakao.com/oauth/authorize"
토큰_주소 = "https://kauth.kakao.com/oauth/token"
보내기_주소 = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
토큰정보_주소 = "https://kapi.kakao.com/v1/user/access_token_info"

# 나에게 보내기에 필요한 동의항목. 이것만 있으면 됩니다.
필요_권한 = "talk_message"

# 기본 리다이렉트. 실제로 열리지 않아도 되고, 주소창의 code 만 씁니다.
기본_리다이렉트 = "https://localhost"

# ★ 텍스트 템플릿의 글자 수 한도입니다. 넘기면 카카오가 거부합니다.
#   텔레그램용 긴 알림을 그대로 보내면 안 되므로 짧게() 로 줄입니다.
글자_한도 = 200

시간제한 = 15


# ==========================================================================
# 내부 도우미
# ==========================================================================

def _POST(주소, 자료, 헤더=None, 제한=시간제한):
    본문 = urllib.parse.urlencode(자료).encode("utf-8")
    req = urllib.request.Request(주소, data=본문, method="POST")
    req.add_header("Content-Type",
                   "application/x-www-form-urlencoded;charset=utf-8")
    for k, v in (헤더 or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=제한) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _오류속내용(e):
    """카카오가 본문에 담아 보내는 실제 사유를 꺼냅니다."""
    try:
        속 = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:                                        # noqa: BLE001
        return "", ""
    # 카카오는 두 가지 모양으로 옵니다.
    #   kapi (보내기)  : {"msg": "...", "code": -401}
    #   kauth (토큰)   : {"error": "invalid_grant", "error_description": "..."}
    if 속.get("code") is not None:
        코드 = str(속["code"])
    else:
        코드 = str(속.get("error") or "")
    말 = str(속.get("msg") or 속.get("error_description")
            or 속.get("error_code") or "")
    return 코드, 말


# 카카오가 자주 내는 오류들. 코드만 보면 무슨 뜻인지 알 수 없어서 풀어씁니다.
_안내 = {
    "-401": "액세스 토큰이 만료되었거나 잘못되었습니다. 리프레시 토큰으로 "
            "다시 발급받아야 합니다.",
    "-402": "'카카오톡 메시지 전송(talk_message)' 동의를 받지 않았습니다. "
            "developers.kakao.com → 카카오 로그인 → 동의항목에서 켜고, "
            "인증 주소로 다시 로그인해 동의하세요.",
    "-403": "이 앱에 없는 권한입니다. 앱 설정에서 '카카오톡 메시지' 를 "
            "사용 중으로 바꾸세요.",
    "-2": "보내는 내용이 잘못되었습니다. 글자 수(200자) 또는 링크 도메인을 "
          "확인하세요.",
    "invalid_grant": "리프레시 토큰이 만료되었거나 이미 쓴 code 입니다. "
                     "브라우저 로그인을 다시 해서 새 code 를 받으세요.",
    "invalid_client": "REST API 키 또는 client_secret 이 맞지 않습니다.",
    "invalid_request": "요청 값이 잘못되었습니다. Redirect URI 가 앱에 "
                       "등록한 것과 **글자 하나까지 같아야** 합니다.",
}


def 오류설명(e) -> str:
    if isinstance(e, urllib.error.HTTPError):
        코드, 말 = _오류속내용(e)
        도움 = _안내.get(코드, "")
        조각 = [f"카카오 응답 {e.code}"]
        if 코드:
            조각.append(f"(코드 {코드})")
        if 도움:
            조각.append(도움)
        elif 말:
            조각.append(말)
        if 도움 and 말:
            조각.append(f"[카카오 원문: {말}]")
        return " ".join(조각)
    if isinstance(e, urllib.error.URLError):
        return f"카카오에 연결하지 못했습니다 ({e.reason})."
    return f"{type(e).__name__}: {e}"


# ==========================================================================
# 1. 처음 한 번 — 브라우저 로그인
# ==========================================================================

def 인증주소(rest키, 리다이렉트=기본_리다이렉트) -> str:
    """브라우저에서 열 주소. 로그인하면 주소창에 ?code=… 가 붙습니다."""
    묶음 = urllib.parse.urlencode({
        "client_id": str(rest키 or "").strip(),
        "redirect_uri": str(리다이렉트 or 기본_리다이렉트).strip(),
        "response_type": "code",
        "scope": 필요_권한,
    })
    return f"{인증_주소}?{묶음}"


def code_꺼내기(붙여넣은것) -> str:
    """주소를 통째로 붙여넣어도 code 만 골라냅니다.

    사용자가 `https://localhost/?code=abcd` 를 그대로 붙이는 일이 흔해서,
    주소든 code 든 다 받아 줍니다.
    """
    글 = str(붙여넣은것 or "").strip()
    if not 글:
        return ""
    if "code=" in 글:
        조각 = urllib.parse.urlparse(글)
        물음표뒤 = urllib.parse.parse_qs(조각.query or "")
        if 물음표뒤.get("code"):
            return 물음표뒤["code"][0].strip()
        # 주소 형태가 아니어도 code= 뒤를 잘라 봅니다
        return 글.split("code=", 1)[1].split("&")[0].strip()
    return 글


def 토큰_받기(rest키, code, 리다이렉트=기본_리다이렉트, 시크릿=None) -> tuple:
    """(액세스토큰, 리프레시토큰, 리프레시만료초, 오류)

    code 는 **한 번만** 쓸 수 있습니다. 실패하면 브라우저 로그인을 다시 해서
    새 code 를 받아야 합니다.
    """
    깨끗한code = code_꺼내기(code)
    if not rest키:
        return None, None, 0, "REST API 키가 없습니다."
    if not 깨끗한code:
        return None, None, 0, "code 가 없습니다. 인증 주소로 로그인한 뒤 "\
                             "주소창의 code 를 넣으세요."
    자료 = {
        "grant_type": "authorization_code",
        "client_id": str(rest키).strip(),
        "redirect_uri": str(리다이렉트 or 기본_리다이렉트).strip(),
        "code": 깨끗한code,
    }
    if 시크릿:
        자료["client_secret"] = str(시크릿).strip()
    try:
        결과 = _POST(토큰_주소, 자료)
    except Exception as e:                                   # noqa: BLE001
        return None, None, 0, 오류설명(e)

    액세스 = 결과.get("access_token")
    리프레시 = 결과.get("refresh_token")
    if not 리프레시:
        return 액세스, None, 0, ("리프레시 토큰이 오지 않았습니다. "
                               "scope 에 talk_message 가 들어갔는지 확인하세요.")
    return 액세스, 리프레시, int(결과.get("refresh_token_expires_in") or 0), None


# ==========================================================================
# 2. 매번 — 액세스 토큰 새로 받기
# ==========================================================================

def 토큰_갱신(rest키, 리프레시, 시크릿=None) -> tuple:
    """(액세스토큰, 새리프레시 or None, 액세스만료초, 오류)

    ★ 새리프레시 가 None 이 아니면 **꼭 저장하세요.**
      카카오는 리프레시 토큰의 남은 기간이 1개월 미만일 때만 새 것을
      내려줍니다. 그때 저장하지 않으면 2개월 뒤 조용히 끊어집니다.
    """
    if not rest키:
        return None, None, 0, "REST API 키가 없습니다."
    if not 리프레시:
        return None, None, 0, ("리프레시 토큰이 없습니다. 화면의 "
                              "'카카오 연결하기' 를 먼저 한 번 하세요.")
    자료 = {
        "grant_type": "refresh_token",
        "client_id": str(rest키).strip(),
        "refresh_token": str(리프레시).strip(),
    }
    if 시크릿:
        자료["client_secret"] = str(시크릿).strip()
    try:
        결과 = _POST(토큰_주소, 자료)
    except Exception as e:                                   # noqa: BLE001
        return None, None, 0, 오류설명(e)

    액세스 = 결과.get("access_token")
    if not 액세스:
        return None, None, 0, "액세스 토큰이 오지 않았습니다."
    # refresh_token 은 갱신됐을 때만 들어옵니다
    새리프레시 = 결과.get("refresh_token") or None
    return 액세스, 새리프레시, int(결과.get("expires_in") or 0), None


def 토큰_정보(액세스토큰) -> tuple:
    """(정보, 오류). 연결이 살아 있는지 확인하는 데 씁니다."""
    if not 액세스토큰:
        return None, "액세스 토큰이 없습니다."
    req = urllib.request.Request(토큰정보_주소)
    req.add_header("Authorization", f"Bearer {str(액세스토큰).strip()}")
    try:
        with urllib.request.urlopen(req, timeout=시간제한) as resp:
            결과 = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                   # noqa: BLE001
        return None, 오류설명(e)
    return {
        "회원번호": str(결과.get("id") or ""),
        "앱번호": str(결과.get("app_id") or ""),
        "남은초": int(결과.get("expires_in") or 0),
    }, None


# ==========================================================================
# 3. 보내기
# ==========================================================================

def 짧게(글, 한도=글자_한도) -> str:
    """긴 알림을 카카오 한도(200자)에 맞게 줄입니다.

    가운데를 자르면 제일 중요한 가격이 사라질 수 있어서, **줄 단위로
    뒤에서부터 버립니다.** 앞줄(호텔·날짜·가격)이 남습니다.
    """
    글 = str(글 or "")
    # 텔레그램용 HTML 표시를 벗깁니다
    for a, b in (("<b>", ""), ("</b>", ""), ("<i>", ""), ("</i>", ""),
                 ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        글 = 글.replace(a, b)
    줄들 = [x.rstrip() for x in 글.split("\n")]
    # 빈 줄은 자리만 차지하므로 먼저 없앱니다
    줄들 = [x for x in 줄들 if x.strip()]
    # ★ 마지막 한 줄은 남깁니다. `while 줄들` 로 두면 첫 줄 자체가 한도를
    #   넘을 때 그 줄까지 버려서 **내용이 통째로 사라집니다.**
    while len(줄들) > 1 and len("\n".join(줄들)) > 한도:
        줄들.pop()
    결과 = "\n".join(줄들)
    if len(결과) > 한도:                     # 한 줄이 이미 한도를 넘는 경우
        결과 = 결과[:한도 - 1] + "…"
    return 결과 or "(내용 없음)"


def 나에게_보내기(액세스토큰, 글, 링크=None) -> tuple:
    """(성공, 메시지)

    링크 를 주면 글 아래에 '자세히 보기' 버튼이 붙습니다. 다만 카카오는
    **앱에 등록한 사이트 도메인**만 허용하므로, 등록하지 않은 주소를 넣으면
    거부됩니다. 그래서 기본값은 링크 없음입니다.
    """
    if not 액세스토큰:
        return False, "액세스 토큰이 없습니다."
    본문 = 짧게(글)
    틀 = {"object_type": "text", "text": 본문, "link": {}}
    if 링크:
        틀["link"] = {"web_url": str(링크), "mobile_web_url": str(링크)}
    try:
        결과 = _POST(보내기_주소, {"template_object": json.dumps(
            틀, ensure_ascii=False)},
            헤더={"Authorization": f"Bearer {str(액세스토큰).strip()}"})
    except Exception as e:                                   # noqa: BLE001
        말 = 오류설명(e)
        if 링크:
            말 += (" (링크를 넣어 보냈습니다. 앱 설정 → 플랫폼 → 사이트 "
                  "도메인에 그 주소의 도메인이 등록돼 있어야 합니다)")
        return False, 말
    if 결과.get("result_code") not in (0, None):
        return False, f"카카오가 거부했습니다 (result_code={결과.get('result_code')})"
    return True, "보냈습니다."


# ==========================================================================
# 4. 한 번에 — 갱신하고 보내기
# ==========================================================================

def 갱신하고_보내기(rest키, 리프레시, 글, 시크릿=None, 링크=None) -> tuple:
    """(성공, 메시지, 새리프레시 or None)

    보내는 쪽에서 쓰는 함수입니다. 액세스 토큰을 새로 받아서 보냅니다.

    ★ 새리프레시 가 None 이 아니면 **저장해야 합니다.**
      부르는 쪽에서 Gist 에 넣어 주세요.
    """
    액세스, 새리프레시, _남은초, 오류 = 토큰_갱신(rest키, 리프레시, 시크릿)
    if 오류:
        return False, 오류, 새리프레시
    좋음, 말 = 나에게_보내기(액세스, 글, 링크)
    return 좋음, 말, 새리프레시


def 설정_점검(rest키, 리프레시) -> list:
    """무엇이 빠졌는지 알려줍니다. 빈 목록이면 보낼 수 있습니다."""
    빠짐 = []
    if not str(rest키 or "").strip():
        빠짐.append("REST API 키(kakao_rest_key)")
    if not str(리프레시 or "").strip():
        빠짐.append("리프레시 토큰 — 화면에서 '카카오 연결하기' 를 한 번 하세요")
    return 빠짐
