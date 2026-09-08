"""
==========================================================================
호텔 가격 자동 확인  (GitHub Actions 에서 실행)
==========================================================================
Streamlit 앱은 아무도 안 보면 잠들기 때문에, 가격 확인을 앱에 맡길 수
없습니다. 이 파일이 GitHub Actions 에서 정해진 시간마다 대신 돕니다.

  [비공개 Gist]  감시 조건 읽기  →  RapidAPI 조회  →  조건 판정
        ↑                                                  ↓
     가격 이력 쓰기  ←──────────────────  텔레그램 알림 보내기

Gist 를 거치기 때문에 앱 화면과 자동 확인이 **같은 자료**를 봅니다.
화면에서 조건을 고치면 다음 자동 확인부터 반영되고, 자동 확인이 쌓은
가격은 화면의 추이 차트에 그대로 나옵니다.

--------------------------------------------------------------------------
필요한 환경변수 (GitHub → Settings → Secrets and variables → Actions)
--------------------------------------------------------------------------
  RAPIDAPI_KEY        RapidAPI 키              (필수)
  RAPIDAPI_HOST       API 호스트                (없으면 기본값)
  GIST_TOKEN          gist 권한 토큰            (필수)
  GIST_ID             자료가 든 Gist id         (필수)

  ※ GitHub 은 `GITHUB_` 으로 시작하는 이름을 Actions Secret 으로 만들지
    못하게 막아 두었습니다(예약된 접두사). 그래서 `GIST_TOKEN` 입니다.
    Actions 가 기본으로 주는 GITHUB_TOKEN 은 Gist 에 접근할 수 없어서
    쓸 수 없고, gist 권한을 준 개인 토큰(PAT)이 따로 필요합니다.

  TELEGRAM_TOKEN      봇 토큰                   (필수)
  TELEGRAM_CHAT_ID    대화방 id                 (필수)

  DRY_RUN=1           조회만 하고 Gist 저장·알림을 하지 않습니다 (시험용)

--------------------------------------------------------------------------
직접 돌려 보기
--------------------------------------------------------------------------
  Windows :  set RAPIDAPI_KEY=...  &&  py -3 scripts\\hotel_check.py
  그 외    :  RAPIDAPI_KEY=... python3 scripts/hotel_check.py
==========================================================================
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

# engines/ 를 찾을 수 있게 저장소 뿌리를 경로에 넣습니다
뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)

from engines import hotel as HT  # noqa: E402

저장파일 = "hotel.json"          # storage.파일이름("hotel") 과 같아야 합니다
GIST_API = "https://api.github.com/gists"


def _출력_준비():
    """윈도우 콘솔에서 한글이 깨지는 것을 막습니다.

    GitHub Actions(리눅스)는 UTF-8 이라 문제가 없지만, 내 PC 에서
    직접 돌려 볼 때 cp949 콘솔이면 한글이 전부 물음표로 나옵니다.
    """
    for 흐름 in (sys.stdout, sys.stderr):
        try:
            흐름.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def 알림글(*조각):
    """Actions 로그에 남깁니다. 비밀값은 절대 넣지 마세요."""
    print(*조각, flush=True)


def 환경(이름, 기본=""):
    return (os.environ.get(이름, "") or "").strip() or 기본


# ==========================================================================
# Gist 읽기 / 쓰기  (storage.py 와 같은 방식. streamlit 없이 다시 구현)
# ==========================================================================

def _gist요청(주소, 토큰, 방식="GET", 본문=None, 시간제한=20):
    데이터 = json.dumps(본문).encode("utf-8") if 본문 is not None else None
    req = urllib.request.Request(주소, data=데이터, method=방식)
    req.add_header("Authorization", f"Bearer {토큰}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "personal-dashboard-hotel-watch")
    if 데이터 is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gist_읽기(토큰, 아이디):
    """(설정, 오류)"""
    try:
        결과 = _gist요청(f"{GIST_API}/{아이디}", 토큰)
    except urllib.error.HTTPError as e:
        안내 = {401: "토큰이 잘못되었거나 만료되었습니다.",
              403: "토큰에 gist 권한이 없습니다.",
              404: "Gist 를 찾을 수 없습니다. GIST_ID 를 확인하세요."}
        return None, f"Gist 응답 {e.code}. {안내.get(e.code, '')}".strip()
    except Exception as e:                                   # noqa: BLE001
        return None, f"Gist 를 읽지 못했습니다: {type(e).__name__}: {e}"

    파일들 = 결과.get("files") or {}
    정보 = 파일들.get(저장파일)
    if not 정보:
        있는것 = ", ".join(sorted(파일들)) or "(없음)"
        return None, (f"Gist 안에 {저장파일} 이 없습니다. 앱에서 호텔 가격 알림 "
                      f"화면을 열고 한 번 저장하세요. 지금 있는 파일: {있는것}")

    내용 = 정보.get("content") or ""
    if 정보.get("truncated") and 정보.get("raw_url"):
        try:
            with urllib.request.urlopen(정보["raw_url"], timeout=20) as r:
                내용 = r.read().decode("utf-8")
        except Exception as e:                               # noqa: BLE001
            return None, f"큰 파일을 받지 못했습니다: {e}"
    try:
        return json.loads(내용 or "{}"), None
    except json.JSONDecodeError as e:
        return None, f"{저장파일} 이 올바른 JSON 이 아닙니다: {e}"


def gist_쓰기(토큰, 아이디, 설정):
    """(성공, 오류). 그 파일만 바꾸고 Gist 의 다른 파일은 건드리지 않습니다."""
    글 = json.dumps(설정, ensure_ascii=False, indent=2, default=str)
    try:
        _gist요청(f"{GIST_API}/{아이디}", 토큰, "PATCH",
                {"files": {저장파일: {"content": 글}}})
    except Exception as e:                                   # noqa: BLE001
        return False, f"Gist 에 쓰지 못했습니다: {type(e).__name__}: {e}"
    return True, None


# ==========================================================================
# 본체
# ==========================================================================

def 실행() -> int:
    _출력_준비()
    시험만 = 환경("DRY_RUN") in ("1", "true", "TRUE", "yes")

    RAPID키 = 환경("RAPIDAPI_KEY")
    호스트 = 환경("RAPIDAPI_HOST", HT.기본_호스트)
    # 예전 이름(GITHUB_GIST_TOKEN)도 받아 줍니다. Actions Secret 으로는
    # 만들 수 없는 이름이지만, 내 PC 에서 시험할 때 쓸 수 있습니다.
    깃토큰 = 환경("GIST_TOKEN") or 환경("GITHUB_GIST_TOKEN")
    기스트 = 환경("GIST_ID")
    텔레토큰 = 환경("TELEGRAM_TOKEN")
    텔레방 = 환경("TELEGRAM_CHAT_ID")

    빠짐 = [이름 for 이름, 값 in (("RAPIDAPI_KEY", RAPID키),
                              ("GIST_TOKEN", 깃토큰),
                              ("GIST_ID", 기스트)) if not 값]
    if 빠짐:
        알림글("!! 필요한 값이 없습니다:", ", ".join(빠짐))
        알림글("   GitHub 저장소 → Settings → Secrets and variables → Actions "
              "에서 추가하세요.")
        return 1

    알림글(f"== 호텔 가격 자동 확인 {datetime.now():%Y-%m-%d %H:%M} ==")
    알림글(f"   API 호스트: {호스트}")
    if 시험만:
        알림글("   DRY_RUN — 저장도 알림도 하지 않습니다")

    설정, 오류 = gist_읽기(깃토큰, 기스트)
    if 오류:
        알림글("!!", 오류)
        return 1

    감시 = 설정.get("감시") or []
    이력 = list(설정.get("이력") or [])
    상태 = dict(설정.get("상태") or {})
    통화 = str(설정.get("통화") or HT.기본_통화).upper()
    알림켬 = bool(설정.get("알림켬", True))

    if not 감시:
        알림글("   감시할 것이 없습니다. 앱에서 감시 조건을 넣고 저장하세요.")
        return 0

    할것, 건너뜀 = [], []
    for 행 in 감시:
        정리 = HT.행_정리(행)
        if not 정리["사용"]:
            건너뜀.append((정리["이름"], "쓰기 꺼짐"))
            continue
        빠진것 = HT.부족한것(정리)
        if 빠진것:
            건너뜀.append((정리["이름"], ", ".join(빠진것)))
            continue
        할것.append(정리)

    for 이름, 이유 in 건너뜀:
        알림글(f"   - 건너뜀: {이름} ({이유})")
    if not 할것:
        알림글("   확인할 수 있는 감시가 없습니다.")
        return 0

    알림글(f"   {len(할것)}건 확인합니다.")

    보낼것, 실패수, 성공수 = [], 0, 0
    for 정리 in 할것:
        답 = HT.한줄_확인(정리, 상태, 이력, RAPID키, 호스트, 통화)
        이름 = 정리["이름"]
        if 답["오류"]:
            실패수 += 1
            알림글(f"   x {이름}: {답['오류']}")
            continue
        성공수 += 1
        이력 = 답["새이력"]
        상태[이름] = 답["새상태"]
        요약 = 답["요약"] or {}
        판정 = 답["판정"] or {}
        꼬리 = ""
        if 요약.get("최저"):
            꼬리 = f" (최저 {요약['최저']:,.0f})"
        알림글(f"   o {이름}: {답['최저가']:,.0f}원{꼬리}"
              f" — {답['호텔'][:40]}")
        if 판정.get("알림"):
            보낼것.append((정리, 답))
            알림글(f"     -> 알림 조건 충족: {'; '.join(판정['이유들'])}")
        elif 판정.get("보류"):
            알림글(f"     -> {판정['보류']}")

    # ---- 알림 채널 준비 ----
    채널 = {"텔레그램": {"토큰": 텔레토큰, "방": 텔레방}}
    쓸것 = HT.쓸_수_있는_채널(채널)
    알림글("   알림 채널: " + (", ".join(쓸것) if 쓸것 else "없음"))

    # ---- 알림 보내기 ----
    보낸수 = 0
    if 보낼것 and not 알림켬:
        알림글(f"   알림 {len(보낼것)}건이 있지만 앱에서 '알림 보내기' 가 "
              "꺼져 있습니다.")
    elif 보낼것 and not 쓸것:
        알림글(f"   알림 {len(보낼것)}건이 있지만 보낼 채널이 없습니다. "
              "TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 를 넣으세요.")
    elif 보낼것 and 시험만:
        알림글(f"   DRY_RUN — 알림 {len(보낼것)}건을 보내지 않았습니다.")
    else:
        for 정리, 답 in 보낼것:
            수, 결과들, _새것 = HT.알림_보내기(
                채널, HT.알림_문장(정리, 답["최저가"], 답["판정"], 답["요약"]))

            for 채널이름, 좋음, 말 in 결과들:
                알림글(f"     {'o' if 좋음 else 'x'} {채널이름}"
                      + ("" if 좋음 else f": {말}"))
            보낸수 += 수

            # 못 보냈으면 '알렸다' 는 기록을 지웁니다.
            # 안 지우면 다음 번에 더 싸지지 않는 한 영원히 조용해집니다.
            if 수 == 0:
                기록 = 상태.get(정리["이름"]) or {}
                기록.pop("마지막알림가", None)
                기록.pop("마지막알림일", None)
                상태[정리["이름"]] = 기록

    # ---- Gist 에 되쓰기 ----
    if 시험만:
        알림글("   DRY_RUN — Gist 에 쓰지 않았습니다.")
    else:
        설정["이력"] = 이력
        설정["상태"] = 상태
        좋음, 오류 = gist_쓰기(깃토큰, 기스트, 설정)
        if not 좋음:
            알림글("!!", 오류)
            알림글("   가격은 확인했지만 이력을 남기지 못했습니다.")
            return 1
        알림글(f"   Gist 저장 완료 (이력 {len(이력)}줄)")

    알림글(f"== 끝: 확인 {성공수}건 / 실패 {실패수}건 / 알림 {보낸수}건 ==")

    # 전부 실패했을 때만 빨간불을 켭니다. 한두 건 실패는 API 사정일 수 있어
    # 매번 실패 메일이 오면 오히려 무시하게 됩니다.
    if 성공수 == 0 and 실패수 > 0:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(실행())
    except KeyboardInterrupt:
        sys.exit(130)
