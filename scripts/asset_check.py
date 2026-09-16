"""
==========================================================================
자산 현황 매일 요약  (GitHub Actions 에서 실행)
==========================================================================
매일 아침 계좌별(일반·연금저축·퇴직연금·ISA …) 평가액과 어제·이달 1일
대비 증감을 텔레그램으로 보냅니다.

  [비공개 Gist]  종목 목록 읽기  →  시세 조회  →  계좌별 합계
        ↑                                              ↓
   오늘 스냅샷 저장  ←────────────  텔레그램 전송

★ 자산배분 화면은 **종목 목록만** 저장하고 평가액은 볼 때마다 새로
  계산합니다. 그래서 "어제 대비" 를 하려면 누군가 매일 그날의 값을
  적어 두어야 합니다 — 그 일을 이 스크립트가 합니다. 오늘 계산한
  값을 Gist 의 portfolio_history.json 에 쌓아 두고, 내일 그것과
  견줍니다. 그래서 **처음 돌린 날에는 비교 줄이 나오지 않습니다.**

--------------------------------------------------------------------------
필요한 환경변수 (GitHub → Settings → Secrets and variables → Actions)
--------------------------------------------------------------------------
  TELEGRAM_TOKEN      봇 토큰                   (필수)
  TELEGRAM_CHAT_ID    대화방 id                 (필수)
  GIST_TOKEN          gist 권한 토큰            (필수 — 자료를 읽고 씁니다)
  GIST_ID             자료가 든 Gist id         (필수)

  ※ 환율 알림과 달리 Gist 가 꼭 필요합니다. 내 종목 목록은 공개 자료가
    아니라 앱이 저장해 둔 내 자료이기 때문입니다.

  DRY_RUN=1           계산만 하고 저장·전송을 하지 않습니다 (시험용)

--------------------------------------------------------------------------
직접 돌려 보기
--------------------------------------------------------------------------
  Windows :  set GIST_TOKEN=...  &&  py -3 scripts\\asset_check.py
==========================================================================
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)

from engines import hotel as HT  # noqa: E402
from engines import portfolio as PF  # noqa: E402
#  ★ 텔레그램 전송 함수는 engines/hotel.py 에 있습니다. 일반적인 HTTP
#    요청이라 그대로 가져다 씁니다 (환율 스크립트와 같은 방식).

자산파일 = "portfolio.json"          # 자산배분 화면이 저장하는 파일
기록파일 = "portfolio_history.json"  # 이 스크립트가 쌓는 스냅샷
보관일수 = 400                        # 1년 조금 넘게만 남깁니다
GIST_API = "https://api.github.com/gists"


def _출력_준비():
    for 흐름 in (sys.stdout, sys.stderr):
        try:
            흐름.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def 알림글(*조각):
    print(*조각, flush=True)


def 오류글(글):
    """실패 이유를 GitHub Actions 의 Annotations 칸에도 띄웁니다."""
    한줄 = str(글).replace("\r", " ").replace("\n", " ")
    print(f"::error::{한줄}", flush=True)
    알림글(f"!! {한줄}")


def 환경(이름, 기본=""):
    return (os.environ.get(이름, "") or "").strip() or 기본


# ==========================================================================
# Gist 읽기 / 쓰기
# ==========================================================================

def _gist요청(주소, 토큰, 방식="GET", 본문=None, 시간제한=20):
    데이터 = json.dumps(본문).encode("utf-8") if 본문 is not None else None
    req = urllib.request.Request(주소, data=데이터, method=방식)
    req.add_header("Authorization", f"Bearer {토큰}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "personal-dashboard-asset-report")
    if 데이터 is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gist_읽기(토큰, 아이디) -> tuple:
    """(파일이름: 내용dict, 오류). 없는 파일은 그냥 빠집니다."""
    try:
        결과 = _gist요청(f"{GIST_API}/{아이디}", 토큰)
    except urllib.error.HTTPError as e:
        안내 = {401: "토큰이 잘못되었거나 만료되었습니다.",
              403: "토큰에 gist 권한이 없습니다.",
              404: "Gist 를 찾을 수 없습니다. GIST_ID 를 확인하세요."}
        return {}, f"Gist 응답 {e.code}. {안내.get(e.code, '')}".strip()
    except Exception as e:                                   # noqa: BLE001
        return {}, f"Gist 를 읽지 못했습니다: {type(e).__name__}: {e}"

    파일들 = 결과.get("files") or {}
    담긴것 = {}
    for 이름 in (자산파일, 기록파일):
        정보 = 파일들.get(이름)
        if not 정보:
            continue
        내용 = 정보.get("content") or ""
        if 정보.get("truncated") and 정보.get("raw_url"):
            try:
                with urllib.request.urlopen(정보["raw_url"], timeout=20) as r:
                    내용 = r.read().decode("utf-8")
            except Exception as e:                           # noqa: BLE001
                return {}, f"큰 파일을 받지 못했습니다: {e}"
        try:
            담긴것[이름] = json.loads(내용 or "{}")
        except json.JSONDecodeError as e:
            return {}, f"{이름} 이 올바른 JSON 이 아닙니다: {e}"
    return 담긴것, None


def gist_쓰기(토큰, 아이디, 이름, 자료) -> tuple:
    """그 파일 하나만 바꿉니다. Gist 의 다른 파일은 건드리지 않습니다."""
    글 = json.dumps(자료, ensure_ascii=False, indent=2, default=str)
    try:
        _gist요청(f"{GIST_API}/{아이디}", 토큰, "PATCH",
                {"files": {이름: {"content": 글}}})
    except Exception as e:                                   # noqa: BLE001
        return False, f"Gist 에 쓰지 못했습니다: {type(e).__name__}: {e}"
    return True, None


# ==========================================================================
# 스냅샷 고르기
# ==========================================================================

def 어제것(스냅샷들, 오늘날짜) -> dict:
    """오늘 이전 중 가장 최근 것. (주말·휴일이면 며칠 전 것이 됩니다)"""
    이전 = [s for s in 스냅샷들 if str(s.get("날짜", "")) < 오늘날짜]
    return max(이전, key=lambda s: s["날짜"]) if 이전 else {}


def 월초것(스냅샷들, 오늘날짜) -> dict:
    """이번 달 1일 이후 중 가장 이른 것.

    1일에 실행이 밀렸거나 그날 자료가 없을 수 있어서, 이번 달에 처음
    남은 기록을 '이달 기준' 으로 씁니다. 그 값이 오늘 것뿐이면(이번 달
    첫 실행) 비교할 게 없으므로 빈 dict 를 돌려줍니다.
    """
    달첫날 = 오늘날짜[:8] + "01"
    이번달 = [s for s in 스냅샷들
            if 달첫날 <= str(s.get("날짜", "")) < 오늘날짜]
    return min(이번달, key=lambda s: s["날짜"]) if 이번달 else {}


# ==========================================================================
# 본체
# ==========================================================================

def 실행() -> int:
    _출력_준비()
    시험만 = 환경("DRY_RUN") in ("1", "true", "TRUE", "yes")

    텔레토큰 = 환경("TELEGRAM_TOKEN")
    텔레방 = 환경("TELEGRAM_CHAT_ID")
    깃토큰 = 환경("GIST_TOKEN") or 환경("GITHUB_GIST_TOKEN")
    기스트 = 환경("GIST_ID")

    빠짐 = [이름 for 이름, 값 in (("TELEGRAM_TOKEN", 텔레토큰),
                              ("TELEGRAM_CHAT_ID", 텔레방),
                              ("GIST_TOKEN", 깃토큰),
                              ("GIST_ID", 기스트)) if not 값]
    if 빠짐:
        오류글(f"{', '.join(빠짐)} 가 GitHub Actions Secrets 에 없습니다. "
             "저장소 Settings > Secrets and variables > Actions 에서 "
             "추가하세요 (Streamlit Cloud 의 Secrets 와는 별개입니다).")
        return 1

    알림글(f"== 자산 현황 요약 {datetime.now():%Y-%m-%d %H:%M} ==")
    if 시험만:
        알림글("   DRY_RUN — 저장도 전송도 하지 않습니다")

    담긴것, 오류 = gist_읽기(깃토큰, 기스트)
    if 오류:
        오류글(오류)
        return 1

    자산 = 담긴것.get(자산파일)
    if not 자산:
        오류글(f"Gist 안에 {자산파일} 이 없습니다. 앱에서 자산배분 화면을 "
             "열고 한 번 저장하세요.")
        return 1

    종목들 = [r for r in (자산.get("종목") or []) if isinstance(r, dict)]
    if not 종목들:
        오류글("자산배분에 저장된 종목이 없습니다.")
        return 1
    알림글(f"   종목 {len(종목들)}개")

    # ---- 시세·환율 ----
    try:
        환율 = PF.환율_조회()
        알림글(f"   환율 {환율:,.2f}원/달러")
    except Exception as e:                                   # noqa: BLE001
        환율 = PF.기본환율
        알림글(f"   환율 조회 실패({e}) — 기본값 {환율:,.0f}원 사용")

    시세맵, 시세실패 = PF.시세_모으기(종목들)
    알림글(f"   시세 {len(시세맵)}건 조회"
          + (f" / 실패 {len(시세실패)}건" if 시세실패 else ""))
    for 티커, 말 in 시세실패[:5]:
        알림글(f"     x {티커}: {말}")

    오늘 = PF.현황_스냅샷(종목들, 환율, 시세맵)
    알림글(f"   총액 {PF.금액_한글(오늘['총액'])}")
    for 계좌, 금액 in sorted(오늘["계좌"].items(), key=lambda x: -x[1]):
        알림글(f"     · {계좌}: {PF.금액_한글(금액)}")

    # ---- 예전 기록과 견주기 ----
    기록 = 담긴것.get(기록파일) or {}
    스냅샷들 = [s for s in (기록.get("스냅샷") or []) if isinstance(s, dict)]
    오늘날짜 = 오늘["날짜"]
    본문 = PF.텔레그램_자산요약(오늘, 어제것(스냅샷들, 오늘날짜),
                         월초것(스냅샷들, 오늘날짜))
    본문 += "\n\n🤖 GitHub Actions 자동 발송"

    if 시험만:
        알림글("")
        알림글(본문)
        알림글("")
        알림글("   DRY_RUN — 보내지 않았습니다.")
        return 0

    좋음, 말 = HT.텔레그램_보내기(텔레토큰, 텔레방, 본문)
    if not 좋음:
        오류글(f"텔레그램 전송 실패: {말}")
        return 1
    알림글("   전송 완료")

    # ---- 오늘 값을 남깁니다 (같은 날 두 번 돌리면 덮어씁니다) ----
    남길것 = [s for s in 스냅샷들 if str(s.get("날짜")) != 오늘날짜]
    남길것.append(오늘)
    남길것.sort(key=lambda s: str(s.get("날짜")))
    기록["스냅샷"] = 남길것[-보관일수:]
    좋음, 오류 = gist_쓰기(깃토큰, 기스트, 기록파일, 기록)
    if not 좋음:
        오류글(f"{오류} (알림은 보냈지만 오늘 값을 남기지 못했습니다 — "
             "내일 '어제 대비' 가 안 나옵니다)")
        return 1
    알림글(f"   기록 저장 완료 (총 {len(기록['스냅샷'])}일치)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(실행())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:                                   # noqa: BLE001
        import traceback
        오류글(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
