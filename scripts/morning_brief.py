"""
==========================================================================
아침 브리핑  (GitHub Actions 에서 실행)
==========================================================================
매일 아침 환율과 자산 현황을 **한 통으로** 묶어 텔레그램으로 보냅니다.

  [비공개 Gist]  종목 목록·목표 비중 읽기
        ↓
  시세·환율 조회  →  계좌별 합계 · 기여도 · 리밸런싱 신호
        ↓
  텔레그램 전송  →  오늘 스냅샷 저장 (내일 '어제 대비' 에 씀)

--------------------------------------------------------------------------
왜 세 번 예약하나
--------------------------------------------------------------------------
GitHub 예약 실행은 정시에 오지 않습니다. 매시 정각에 작업이 몰려 길게는
한두 시간까지 밀립니다(실제로 08:00 설정이 09:47 에 돈 적이 있습니다).
그래서 06:50 · 07:10 · 07:30 세 번 예약해 두고, **그날 이미 보냈으면
그냥 끝냅니다.** 셋 중 하나만 제때 돌면 7시 전후에 도착합니다.

--------------------------------------------------------------------------
필요한 환경변수 (GitHub → Settings → Secrets and variables → Actions)
--------------------------------------------------------------------------
  TELEGRAM_TOKEN      봇 토큰                   (필수)
  TELEGRAM_CHAT_ID    대화방 id                 (필수)
  GIST_TOKEN          gist 권한 토큰            (필수 — 자료를 읽고 씁니다)
  GIST_ID             자료가 든 Gist id         (필수)

  DRY_RUN=1           계산만 하고 저장·전송을 하지 않습니다
  FORCE=1             오늘 이미 보냈어도 다시 보냅니다 (손으로 돌릴 때)
==========================================================================
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)

from engines import brief as BR  # noqa: E402
from engines import fx as FX  # noqa: E402
from engines import hotel as HT  # noqa: E402
from engines import portfolio as PF  # noqa: E402

자산파일 = "portfolio.json"          # 자산배분 화면이 저장하는 파일
기록파일 = "portfolio_history.json"  # 이 스크립트가 쌓는 스냅샷
보관일수 = 400
GIST_API = "https://api.github.com/gists"

# 브리핑에 넣을 통화와 짧은 이름 (첫 번째가 가장 중요한 통화입니다)
통화순서 = [
    ("미국 달러 (USD)", "달러"),
    ("일본 엔 (JPY)", "엔"),
    ("유로 (EUR)", "유로"),
    ("중국 위안 (CNY)", "위안"),
    ("싱가포르 달러 (SGD)", "싱달"),
]

# 리밸런싱 계산에서 뺄 계좌 — 상품 선택이 제한적이라 화면도 기본으로 뺍니다.
# 화면에서 고른 값이 저장돼 있으면 그쪽을 씁니다.
기본_조정계좌 = ["일반"]


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


def 참인가(이름) -> bool:
    return 환경(이름) in ("1", "true", "TRUE", "yes")


# ==========================================================================
# Gist 읽기 / 쓰기
# ==========================================================================

def _gist요청(주소, 토큰, 방식="GET", 본문=None, 시간제한=20):
    데이터 = json.dumps(본문).encode("utf-8") if 본문 is not None else None
    req = urllib.request.Request(주소, data=데이터, method=방식)
    req.add_header("Authorization", f"Bearer {토큰}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "personal-dashboard-morning-brief")
    if 데이터 is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=시간제한) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gist_읽기(토큰, 아이디) -> tuple:
    """({파일이름: 내용}, 오류). 없는 파일은 빠집니다."""
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
    """오늘 이전 중 가장 최근 것 (주말이면 며칠 전 것이 됩니다)."""
    이전 = [s for s in 스냅샷들 if str(s.get("날짜", "")) < 오늘날짜]
    return max(이전, key=lambda s: s["날짜"]) if 이전 else {}


def 월초것(스냅샷들, 오늘날짜) -> dict:
    """이번 달에 남은 가장 이른 기록 (보통 1일)."""
    달첫날 = 오늘날짜[:8] + "01"
    이번달 = [s for s in 스냅샷들
            if 달첫날 <= str(s.get("날짜", "")) < 오늘날짜]
    return min(이번달, key=lambda s: s["날짜"]) if 이번달 else {}


def 주초것(스냅샷들, 오늘날짜) -> dict:
    """이번 주(월요일 이후)에 남은 가장 이른 기록.

    토요일 결산에서 "이번 주 얼마 늘었나" 를 내는 데 씁니다.
    """
    try:
        오늘 = date.fromisoformat(오늘날짜)
    except (TypeError, ValueError):
        return {}
    월요일 = (오늘 - timedelta(days=오늘.weekday())).isoformat()
    이번주 = [s for s in 스냅샷들
            if 월요일 <= str(s.get("날짜", "")) < 오늘날짜]
    return min(이번주, key=lambda s: s["날짜"]) if 이번주 else {}


def 지난달것(스냅샷들, 오늘날짜) -> dict:
    """지난달에 남은 가장 이른 기록 (보통 지난달 1일).

    ★ 월초것() 은 '이번 달' 을 보므로, 매달 1일에는 비교할 게 없습니다
      (오늘이 이번 달의 첫날이니까요). 1일 아침의 '지난달 결산' 은
      지난달 시작과 견줘야 말이 됩니다.
    """
    달첫날 = 오늘날짜[:8] + "01"
    try:
        지난달끝 = date.fromisoformat(달첫날) - timedelta(days=1)
    except (TypeError, ValueError):
        return {}
    지난달첫날 = 지난달끝.replace(day=1).isoformat()
    후보 = [s for s in 스냅샷들
          if 지난달첫날 <= str(s.get("날짜", "")) < 달첫날]
    return min(후보, key=lambda s: s["날짜"]) if 후보 else {}


def 연초것(스냅샷들, 오늘날짜) -> dict:
    """올해 남은 가장 이른 기록."""
    올해첫날 = 오늘날짜[:4] + "-01-01"
    올해 = [s for s in 스냅샷들
          if 올해첫날 <= str(s.get("날짜", "")) < 오늘날짜]
    return min(올해, key=lambda s: s["날짜"]) if 올해 else {}


def 최고찾기(스냅샷들, 오늘날짜) -> tuple:
    """(금액, 날짜) — 오늘 이전까지의 역대 최고."""
    이전 = [s for s in 스냅샷들 if str(s.get("날짜", "")) < 오늘날짜]
    if not 이전:
        return 0.0, None
    최고 = max(이전, key=lambda s: PF._숫자(s.get("총액")))
    return PF._숫자(최고.get("총액")), 최고.get("날짜")


def 구간_머문날수(스냅샷들, 통화이름, 오늘날짜, 싼쪽=True,
            싼기준=15.0, 비싼기준=85.0) -> int:
    """그 통화가 지금 구간에 며칠째 머물고 있는지."""
    날수 = 0
    for s in sorted(스냅샷들, key=lambda x: str(x.get("날짜", "")), reverse=True):
        if str(s.get("날짜", "")) >= 오늘날짜:
            continue
        위치 = (s.get("환율위치") or {}).get(통화이름)
        if 위치 is None:
            break
        안쪽 = (위치 <= 싼기준) if 싼쪽 else (위치 >= 비싼기준)
        if not 안쪽:
            break
        날수 += 1
    return 날수


# ==========================================================================
# 본체
# ==========================================================================

def 실행() -> int:
    _출력_준비()
    시험만 = 참인가("DRY_RUN")
    강제 = 참인가("FORCE")

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

    오늘날짜 = date.today().isoformat()
    알림글(f"== 아침 브리핑 {datetime.now():%Y-%m-%d %H:%M} ==")

    담긴것, 오류 = gist_읽기(깃토큰, 기스트)
    if 오류:
        오류글(오류)
        return 1

    기록 = 담긴것.get(기록파일) or {}
    스냅샷들 = [s for s in (기록.get("스냅샷") or []) if isinstance(s, dict)]

    # ---- 오늘 이미 보냈으면 조용히 끝냅니다 (세 번 예약의 중복 방지) ----
    if not 강제 and not 시험만 and str(기록.get("마지막발송일")) == 오늘날짜:
        알림글("   오늘 이미 보냈습니다. 건너뜁니다.")
        return 0

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
        원달러 = PF.환율_조회()
    except Exception as e:                                   # noqa: BLE001
        원달러 = PF.기본환율
        알림글(f"   환율 조회 실패({e}) — 기본값 {원달러:,.0f}원 사용")
    시세맵, 시세실패 = PF.시세_모으기(종목들)
    알림글(f"   시세 {len(시세맵)}건" + (f" / 실패 {len(시세실패)}건"
                                  if 시세실패 else ""))
    for 티커, 말 in 시세실패[:5]:
        알림글(f"     x {티커}: {말}")

    오늘 = PF.현황_스냅샷(종목들, 원달러, 시세맵)
    알림글(f"   총액 {PF.금액_한글(오늘['총액'])}")

    # ---- 환율 5종 ----
    환율들, 위치기록 = [], {}
    for 이름, 짧은 in 통화순서:
        cur = FX.CURRENCIES.get(이름)
        if not cur:
            continue
        try:
            자료, _출처, _기록 = FX.환율_가져오기(cur, years=3)
            범위 = FX.범위_위치(자료, years=1)
            단기 = {r["라벨"]: r for r in FX.단기_요약(자료)}
        except Exception as e:                               # noqa: BLE001
            알림글(f"     x {짧은}: {e}")
            continue
        현재가 = float(자료["Close"].iloc[-1])
        하루 = 단기.get("1일 전") or {}
        변화글 = ""
        if 하루.get("신뢰"):
            v = 하루["변동률"]
            화살 = "▲" if v > 0.05 else ("▼" if v < -0.05 else "―")
            # 화살표가 방향을 말하므로 숫자에는 부호를 빼야 "▲+5원" 이
            # 되지 않습니다
            금액글 = FX._차이표시(하루["차이"], 현재가, cur["unit"]).lstrip("+-")
            변화글 = f"{화살}{금액글}"
        위치 = 범위.get("퍼센타일")
        if 위치 is not None:
            위치기록[이름] = 위치
        어제스냅 = 어제것(스냅샷들, 오늘날짜)
        환율들.append({
            "이름": 짧은,
            "짧은이름": 짧은,
            "표시가": FX.금액표시(현재가, cur["unit"]),
            "위치": 위치,
            "이전위치": (어제스냅.get("환율위치") or {}).get(이름),
            "하루변화": 변화글,
            "체감": FX.체감_환산(현재가, cur),
            "구간일수": 구간_머문날수(스냅샷들, 이름, 오늘날짜,
                              싼쪽=(위치 is not None and 위치 <= 15)),
        })
    알림글(f"   환율 {len(환율들)}종")
    오늘["환율위치"] = 위치기록

    # ---- 목표 비중 · 리밸런싱 신호 ----
    목표 = 자산.get("목표") or {}
    기준 = 자산.get("목표기준") or PF.목표기준_추측(목표)
    조정계좌 = 자산.get("조정계좌") or 기본_조정계좌
    신호 = PF.리밸런싱_신호(종목들, 목표, 기준, 조정계좌,
                     임계=BR.기본_임계["리밸런싱_괴리"],
                     환율=원달러, 시세맵=시세맵)
    if 목표:
        알림글(f"   목표({기준}) 기준 신호 {len(신호)}건 · "
              f"범위 {', '.join(조정계좌)}")

    # 계좌 블록은 시장(US/KR/COIN), 신호는 자산군으로 셉니다. 국내 상장
    # 해외 ETF 는 두 곳에서 다르게 잡히므로 그 액수를 미리 뽑아 둡니다.
    엇갈린해외 = PF.엇갈린_해외(종목들, 조정계좌, 원달러, 시세맵) if 신호 else 0.0

    # ---- 글 만들기 ----
    어제 = 어제것(스냅샷들, 오늘날짜)
    최고, 최고날 = 최고찾기(스냅샷들, 오늘날짜)
    묶음 = {
        "오늘": 오늘,
        "어제": 어제,
        "주초": 주초것(스냅샷들, 오늘날짜),
        "월초": 월초것(스냅샷들, 오늘날짜),
        "지난달": 지난달것(스냅샷들, 오늘날짜),
        "연초": 연초것(스냅샷들, 오늘날짜),
        "최고": 최고, "최고날": 최고날,
        "기여": PF.기여도(오늘, 어제),
        "신호": 신호,
        "엇갈린해외": 엇갈린해외,
    }
    본문, 모드 = BR.브리핑_만들기(
        묶음, 환율들, 오늘날짜,
        신호범위=f"{'·'.join(조정계좌)} 계좌 · {기준} 기준" if 신호 else "")
    본문 += "\n\n🤖 자동 발송"
    알림글(f"   모드: {모드}")

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

    # ---- 오늘 값 남기기 ----
    남길것 = [s for s in 스냅샷들 if str(s.get("날짜")) != 오늘날짜]
    남길것.append(오늘)
    남길것.sort(key=lambda s: str(s.get("날짜")))
    기록["스냅샷"] = 남길것[-보관일수:]
    기록["마지막발송일"] = 오늘날짜
    좋음, 오류 = gist_쓰기(깃토큰, 기스트, 기록파일, 기록)
    if not 좋음:
        오류글(f"{오류} (알림은 보냈지만 오늘 값을 남기지 못했습니다 — "
             "내일 '어제 대비' 가 안 나옵니다)")
        return 1
    알림글(f"   기록 저장 완료 ({len(기록['스냅샷'])}일치)")
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
