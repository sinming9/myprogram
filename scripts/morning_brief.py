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
import time
from datetime import date, datetime, timedelta, timezone

뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)

from engines import brief as BR  # noqa: E402
from engines import fx as FX  # noqa: E402
from engines import telegram as TG  # noqa: E402
from engines import portfolio as PF  # noqa: E402

자산파일 = "portfolio.json"          # 자산배분 화면이 저장하는 파일
기록파일 = "portfolio_history.json"  # 이 스크립트가 쌓는 스냅샷
상태파일 = "brief_state.json"        # 기록을 못 읽은 날 '오늘 보냄' 만 남기는 곳
종목칸_보관일수 = 8                  # 종목별 칸(기여도용)은 최근 며칠치만
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

# 리밸런싱 대상 계좌는 PF.조정계좌_정하기() 가 정합니다 (앱과 같은 규칙).


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


def 경고글(글):
    """보낼 만은 하지만 미심쩍은 것. Annotations 의 노란 칸에 뜹니다."""
    한줄 = str(글).replace("\r", " ").replace("\n", " ")
    print(f"::warning::{한줄}", flush=True)
    알림글(f"?? {한줄}")


def 환경(이름, 기본=""):
    return (os.environ.get(이름, "") or "").strip() or 기본


# 한국은 서머타임이 없어서 UTC+9 고정으로 정확합니다. zoneinfo 를 쓰면
# 윈도우에서는 tzdata 패키지가 따로 있어야 해서 고정 시차를 씁니다.
한국시간 = timezone(timedelta(hours=9), "KST")


def 한국_지금() -> datetime:
    """★ 러너는 UTC 로 돕니다. 예약이 UTC 21:50 에 돌면 한국은 이미
    다음 날 06:50 인데 date.today() 는 아직 전날을 줍니다. 그래서 머리글
    날짜·요일이 매일 하루 밀리고, 토요일 결산이 일요일에, 1일 결산이
    2일에 왔습니다. 또 예약이 UTC 자정을 넘겨 밀리면 같은 한국 아침에
    두 통이 가고 다음 날은 한 통도 안 갔습니다. 날짜는 전부 여기서만
    구합니다."""
    return datetime.now(한국시간)


믿을수없음_실패비중 = 5.0      # 시세 못 받은 금액이 총액의 이만큼(%) 넘으면


def 숫자_점검(오늘: dict, 어제: dict, 환율들: list, 빠진통화: list,
          종목들: list = None) -> tuple:
    """(걸린 것 목록, 믿을 수 있나). 그날 받아 온 **값**을 봅니다.

    ★ 이 알림이 무서운 건 실패할 때가 아니라 실패하지 않고 그럴듯한
      틀린 숫자를 보낼 때입니다. 예전 판본은 "총액 = 계좌 합" 처럼 같은
      반복문에서 같이 더해져 **절대 어긋날 수 없는** 관계를 봐서, 실제로
      일어나는 사고(시세 실패·환율 대체·묵은 자료)는 전부 통과했습니다.
      이제는 실제로 깨지는 것만 봅니다.

    믿을 수 없는 날(총액 0, 시세 실패가 크다, 원달러를 못 받았다)에는
    러너가 비교를 빼고 오늘 값을 기록하지 않습니다. 틀린 총액이 기록에
    남으면 다음 날 '급등', '역대 최고' 가 연달아 거짓으로 나갑니다.
    """
    탈, 믿음 = [], True
    총액 = PF._숫자(오늘.get("총액"))
    if 총액 <= 0:
        return ["총액이 0 입니다 (시세 조회가 전부 실패했을 수 있습니다)"], False

    실패 = 오늘.get("시세실패") or {}
    if 실패.get("개수"):
        비중 = PF._숫자(실패.get("금액")) / 총액 * 100
        이름들 = ", ".join(str(x) for x in (실패.get("이름들") or [])[:4])
        탈.append(f"시세를 못 받은 종목 {실패['개수']}개 (총액의 {비중:.0f}% · "
                 f"{이름들}) — 입력해 둔 가격으로 계산했습니다")
        if 비중 >= 믿을수없음_실패비중:
            믿음 = False

    if 오늘.get("환율대체"):
        탈.append(f"원달러를 못 받아 {PF._숫자(오늘.get('환율')):,.0f}원으로 "
                 "계산했습니다 (미국 종목 금액이 틀릴 수 있습니다)")
        믿음 = False

    if 빠진통화:
        탈.append("환율을 못 받은 통화: " + ", ".join(빠진통화))
    for 통화 in 환율들 or []:
        if 통화.get("묵음", 0) > 4:
            탈.append(f"{통화['짧은이름']} 환율이 {통화['묵음']}일 전 자료입니다")

    # 어제와 견줘 말이 안 되는 움직임 — 조회 오류일 가능성이 큽니다
    옛총액 = PF._숫자((어제 or {}).get("총액"))
    if 옛총액 > 0 and abs(총액 / 옛총액 - 1) >= 0.3:
        탈.append(f"총액이 어제보다 {(총액 / 옛총액 - 1) * 100:+.0f}% 입니다 "
                 "— 조회 오류일 수 있습니다")
        믿음 = False
    옛종목 = (어제 or {}).get("종목") or {}
    for 열쇠, 칸 in (오늘.get("종목") or {}).items():
        옛, 새 = PF._숫자((옛종목.get(열쇠) or {}).get("금액")), PF._숫자(칸.get("금액"))
        수량같음 = (PF._숫자((옛종목.get(열쇠) or {}).get("수량"))
                  == PF._숫자(칸.get("수량")))
        if 수량같음 and 옛 > 100_000 and (새 < 옛 * 0.1 or 새 > 옛 * 10):
            탈.append(f"{칸.get('이름')} 금액이 하루 만에 "
                     f"{PF.금액_한글(옛)} → {PF.금액_한글(새)} (수량 그대로)")

    이상한시장 = sorted({str(r.get("시장")) for r in 종목들 or []
                    if str(r.get("시장") or "KR").strip().upper()
                    not in PF.시장목록})
    if 이상한시장:
        탈.append(f"알 수 없는 시장 값: {', '.join(이상한시장)}")
    return 탈, 믿음


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
    for 이름 in (자산파일, 기록파일, 상태파일):
        정보 = 파일들.get(이름)
        if not 정보:
            continue
        내용 = 정보.get("content") or ""
        try:
            if 정보.get("truncated") and 정보.get("raw_url"):
                # 1MB 넘는 파일은 API 가 잘라서 주므로 원본 주소로 받습니다.
                # 인증 헤더를 붙이고, 일시 오류는 한 번 더 해 봅니다.
                내용 = _원본_받기(정보["raw_url"], 토큰)
            담긴것[이름] = json.loads(내용 or "{}")
        except Exception as e:                               # noqa: BLE001
            if 이름 == 기록파일:
                # ★ 기록은 '어제 대비' 에만 씁니다. 기록을 못 읽었다고 그날
                #   브리핑을 통째로 안 보내던 걸 바꿉니다 — 비교 없이 보내고,
                #   빈 기록으로 덮어쓰지 않도록 표시를 남깁니다.
                담긴것["_기록실패"] = f"{type(e).__name__}: {e}"
                continue
            return {}, f"{이름} 을 읽지 못했습니다: {type(e).__name__}: {e}"
    return 담긴것, None


def _원본_받기(주소, 토큰, 시도=2) -> str:
    오류 = None
    for 회차 in range(시도):
        req = urllib.request.Request(주소)
        req.add_header("Authorization", f"Bearer {토큰}")
        req.add_header("User-Agent", "personal-dashboard-morning-brief")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8")
        except Exception as e:                               # noqa: BLE001
            오류 = e
            if 회차 + 1 < 시도:
                time.sleep(3)
    raise 오류


def gist_쓰기(토큰, 아이디, 이름, 자료, 시도=3, 잠=time.sleep) -> tuple:
    """(성공, 오류). 502·레이트리밋 같은 일시 오류는 몇 번 다시 해 봅니다.

    ★ 여기가 실패하면 '오늘 보냈다' 는 기록이 안 남아서 20분 뒤 예약이
      같은 브리핑을 또 보냅니다. 그래서 한 번 실패로 포기하지 않습니다.
    """
    # 들여쓰기 없이 저장합니다. 기록 파일이 1MB 를 넘으면 GitHub 가 잘라서
    # 주므로, 작게 유지하는 것 자체가 안전장치입니다.
    글 = json.dumps(자료, ensure_ascii=False, separators=(",", ":"),
                   default=str)
    오류 = ""
    for 회차 in range(1, 시도 + 1):
        try:
            _gist요청(f"{GIST_API}/{아이디}", 토큰, "PATCH",
                    {"files": {이름: {"content": 글}}})
            return True, None
        except urllib.error.HTTPError as e:
            오류 = f"Gist 에 쓰지 못했습니다: HTTP {e.code}"
            if e.code in (401, 403, 404, 422):       # 다시 해도 같은 결과
                break
        except Exception as e:                               # noqa: BLE001
            오류 = f"Gist 에 쓰지 못했습니다: {type(e).__name__}: {e}"
        if 회차 < 시도:
            잠(3 * 회차)
    return False, 오류


# ==========================================================================
# 스냅샷 고르기
# ==========================================================================

def 어제것(스냅샷들, 오늘날짜) -> dict:
    """오늘 이전 중 가장 최근 것 (주말이면 며칠 전 것이 됩니다)."""
    이전 = [s for s in 스냅샷들 if str(s.get("날짜", "")) < 오늘날짜]
    return max(이전, key=lambda s: str(s.get("날짜", ""))) if 이전 else {}


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
    """올해 남은 가장 이른 기록. 1월 1일이면 작년 것.

    ★ 1월 1일 아침의 월간 결산은 '지난 한 해' 를 말해야 합니다. 예전에는
      올해(=오늘부터) 기록만 봐서 그날은 비었고, 결국 1년 결과는 어느
      날에도 나오지 않았습니다.
    """
    if 오늘날짜[5:] == "01-01":
        작년 = str(int(오늘날짜[:4]) - 1)
        후보 = [s for s in 스냅샷들
              if f"{작년}-01-01" <= str(s.get("날짜", "")) < 오늘날짜]
        return min(후보, key=lambda s: s["날짜"]) if 후보 else {}
    올해첫날 = 오늘날짜[:4] + "-01-01"
    올해 = [s for s in 스냅샷들
          if 올해첫날 <= str(s.get("날짜", "")) < 오늘날짜]
    return min(올해, key=lambda s: s["날짜"]) if 올해 else {}


def 최고찾기(스냅샷들, 오늘날짜) -> tuple:
    """(금액, 날짜) — 남아 있는 스냅샷 안에서의 최고."""
    이전 = [s for s in 스냅샷들 if str(s.get("날짜", "")) < 오늘날짜]
    if not 이전:
        return 0.0, None
    최고 = max(이전, key=lambda s: PF._숫자(s.get("총액")))
    return PF._숫자(최고.get("총액")), 최고.get("날짜")


def 최고_기록(기록, 스냅샷들, 오늘날짜) -> tuple:
    """(금액, 날짜) — 역대 최고. 기록에 따로 둔 값과 스냅샷 중 큰 쪽.

    ★ 스냅샷은 400건만 남기므로, 하락장이 그보다 길면 진짜 최고점이
      잘려 나가 더 낮은 총액에도 '역대 최고 경신' 이 나갔습니다. 최고는
      잘라내기와 상관없이 기록['최고'] 에 따로 남깁니다.
    """
    저장 = 기록.get("최고") or {}
    창, 창날 = 최고찾기(스냅샷들, 오늘날짜)
    if PF._숫자(저장.get("총액")) >= 창 and str(저장.get("날짜") or "") < 오늘날짜:
        return PF._숫자(저장.get("총액")), 저장.get("날짜")
    return 창, 창날


def 기록_다듬기(스냅샷들, 오늘날짜) -> list:
    """저장 전에 기록을 작게 만듭니다.

    ★ 스냅샷마다 종목별 칸이 다 들어가서 몇 달이면 1MB 를 넘었습니다.
      그러면 GitHub 가 파일을 잘라서 주고, 원본을 한 번 더 받다 실패하면
      그날 브리핑이 통째로 안 나갔습니다. 종목별 칸은 기여도(어제·지난주
      대비)에만 쓰므로 최근 며칠치만 남깁니다.
    """
    try:
        경계 = (date.fromisoformat(오늘날짜)
              - timedelta(days=종목칸_보관일수)).isoformat()
    except ValueError:
        경계 = ""
    결과 = []
    for s in sorted(스냅샷들, key=lambda x: str(x.get("날짜", ""))):
        if str(s.get("날짜", "")) < 경계 and "종목" in s:
            s = {k: v for k, v in s.items() if k != "종목"}
        결과.append(s)
    return 결과[-보관일수:]


def 유령KS_보정(기록, 스냅샷들, 종목들, 조회=None) -> list:
    """옛 코드가 '유령 .KS' 가격으로 남긴 지난 기록을 진짜 가격으로 고칩니다.

    ★ 코스닥 종목 상당수가 야후에 멈춘 '.KS' 항목(2024-07 가격)을 갖고
      있어서, 옛 코드는 힘스를 실제의 2.5배로 계산해 기록에 남겼습니다.
      새 코드가 진짜 가격을 쓰기 시작한 날 '힘스 -260만원' 처럼 가짜
      움직임이 나왔고, 옛 기록과 비교하는 '이번 주'·'지난달' 도 틀립니다.

      옛 코드가 쓴 가격 = .KS 의 멈춘 meta 가격(날마다 같음)
      진짜 가격         = 그 기록 날짜의 .KQ 종가
      차이 × 수량 만큼 총액·계좌·시장·자산군·종목 칸을 고칩니다.

    옛 기록은 '시세실패' 칸이 없는 것으로 알아봅니다(새 코드가 붙임).
    한 번만 돌도록 기록['보정'] 에 표시합니다. 고친 종목 이름 목록을 반환.
    """
    if (기록.get("보정") or {}).get("유령KS"):
        return []
    조회 = 조회 or PF._야후_조회
    옛것 = [s for s in 스냅샷들 if "시세실패" not in s]
    고친것 = []
    본티커 = set()
    for 행 in 종목들:
        티커, 시장 = PF._시세열쇠(행)
        if 시장 != "KR" or not PF.한국_종목코드인가(티커) or 티커 in 본티커:
            continue
        본티커.add(티커)
        try:
            ks = 조회(f"{티커}.KS")
            메타 = ks.get("meta") or {}
            if str(메타.get("exchangeName") or "") in ("", "KSC"):
                continue                               # 진짜 코스피 — 해당 없음
            유령가 = float(메타.get("regularMarketPrice") or 0)
            kq = 조회(f"{티커}.KQ")
        except Exception:                                    # noqa: BLE001
            continue
        종가표 = {}
        for t, v in zip(kq.get("timestamp") or [],
                        ((kq.get("indicators") or {}).get("quote") or [{}])[0]
                        .get("close") or []):
            if v:
                종가표[datetime.fromtimestamp(t, 한국시간).date().isoformat()] = float(v)
        if not 유령가 or not 종가표:
            continue
        날짜들 = sorted(종가표)
        같은티커 = [r for r in 종목들 if PF._시세열쇠(r)[0] == 티커]
        for s in 옛것:
            이전 = [d for d in 날짜들 if d <= str(s.get("날짜"))]
            if not 이전:
                continue
            진짜 = 종가표[이전[-1]]
            for r in 같은티커:
                if r.get("평가액(직접입력)"):
                    continue
                계좌 = str(r.get("계좌") or "기타").strip() or "기타"
                자산군 = str(r.get("자산군") or "기타").strip() or "기타"
                칸 = (s.get("종목") or {}).get(f"{계좌}|{티커}") or {}
                수량 = PF._숫자(칸.get("수량") or r.get("수량"))
                차이 = 수량 * (진짜 - 유령가)
                if abs(차이) < 1:
                    continue
                s["총액"] = PF._숫자(s.get("총액")) + 차이
                if isinstance(s.get("계좌"), dict):
                    s["계좌"][계좌] = PF._숫자(s["계좌"].get(계좌)) + 차이
                시장칸 = (s.get("계좌시장") or {}).get(계좌)
                if isinstance(시장칸, dict):
                    시장칸["KR"] = PF._숫자(시장칸.get("KR")) + 차이
                if isinstance(s.get("자산군"), dict):
                    s["자산군"][자산군] = PF._숫자(s["자산군"].get(자산군)) + 차이
                if 칸:
                    칸["금액"] = PF._숫자(칸.get("금액")) + 차이
                이름 = str(r.get("이름") or 티커)
                if 이름 not in 고친것:
                    고친것.append(이름)
    기록.setdefault("보정", {})["유령KS"] = True
    if 고친것:
        # 역대 최고도 부풀려진 값일 수 있으니 고친 기록에서 다시 구합니다
        기록.pop("최고", None)
    return 고친것


def 최근_위치(스냅샷들, 통화이름, 오늘날짜):
    """그 통화의 위치가 남아 있는 가장 최근 기록의 위치.

    ★ 어제 기록만 보면, 어제 환율 조회가 실패한 통화는 '이전위치 없음'
      이 되어 한 달째 싼 구간인데도 '오늘 들어왔습니다' 가 다시 나갔습니다.
    """
    for s in sorted(스냅샷들, key=lambda x: str(x.get("날짜", "")), reverse=True):
        if str(s.get("날짜", "")) >= 오늘날짜:
            continue
        위치 = (s.get("환율위치") or {}).get(통화이름)
        if 위치 is not None:
            return 위치
    return None


def 구간_머문날수(스냅샷들, 통화이름, 오늘날짜, 오늘위치,
            싼기준=15.0, 비싼기준=85.0) -> int:
    """오늘을 포함해 그 구간에 **연속으로** 며칠째인지. 오늘 구간 밖이면 0.

    ★ 예전 판본의 문제 세 가지를 고쳤습니다.
      · 오늘이 구간 밖이어도 과거를 세서, '50% · 보통' 바로 아래에
        '머무는 중: 달러 5일째' 가 나갔습니다.
      · 오늘을 안 세서 늘 하루 적었습니다.
      · 날이 아니라 기록 개수를 세서, 며칠 빠진 기록도 이어진 것처럼
        셌습니다. 이제는 하루라도 비면 거기서 멈춥니다.
    """
    if 오늘위치 is None:
        return 0
    싼쪽 = 오늘위치 <= 싼기준
    if not 싼쪽 and 오늘위치 < 비싼기준:
        return 0
    날별 = {str(s.get("날짜")): (s.get("환율위치") or {}).get(통화이름)
          for s in 스냅샷들}
    try:
        기대 = date.fromisoformat(오늘날짜) - timedelta(days=1)
    except ValueError:
        return 1
    날수 = 1
    while True:
        위치 = 날별.get(기대.isoformat())
        if 위치 is None or not ((위치 <= 싼기준) if 싼쪽 else (위치 >= 비싼기준)):
            return 날수
        날수 += 1
        기대 -= timedelta(days=1)


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

    지금 = 한국_지금()
    오늘날짜 = 지금.date().isoformat()
    알림글(f"== 아침 브리핑 {지금:%Y-%m-%d %H:%M} (한국시간) ==")

    담긴것, 오류 = gist_읽기(깃토큰, 기스트)
    if 오류:
        오류글(오류)
        return 1

    기록 = 담긴것.get(기록파일) or {}
    # 날짜가 없는 기록(옛 형식·손으로 고친 것)은 비교에 못 쓰므로 뺍니다
    스냅샷들 = [s for s in (기록.get("스냅샷") or [])
            if isinstance(s, dict) and s.get("날짜")]

    # ---- 오늘 이미 보냈으면 조용히 끝냅니다 (세 번 예약의 중복 방지) ----
    보낸날 = {str(기록.get("마지막발송일")),
            str((담긴것.get(상태파일) or {}).get("마지막발송일"))}
    if not 강제 and not 시험만 and 오늘날짜 in 보낸날:
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

    # 옛 코드가 남긴 '유령 .KS' 가격 기록을 한 번 고칩니다 (비교 전에)
    if not 담긴것.get("_기록실패"):
        고친것 = 유령KS_보정(기록, 스냅샷들, 종목들)
        if 고친것:
            알림글(f"   지난 기록 보정 (유령 .KS 가격): {', '.join(고친것)}")

    어제 = 어제것(스냅샷들, 오늘날짜)

    # ---- 환율 5종 (원달러 대체값으로도 쓰므로 먼저) ----
    환율들, 위치기록, 빠진통화 = [], {}, []
    달러현재가 = None
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
            빠진통화.append(짧은)
            continue
        현재가 = float(자료["Close"].iloc[-1])
        묵음 = FX.묵은날수(자료, 오늘날짜)
        if 짧은 == "달러" and 묵음 <= 4:
            달러현재가 = 현재가
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
        # 묵은 자료의 위치는 '오늘' 의 위치가 아니므로 진입 판정·기록에
        # 쓰지 않습니다 (묵은 값이 며칠씩 쌓여 가짜 '머무는 중' 이 됨)
        if 묵음 > 4:
            위치 = None
        if 위치 is not None:
            위치기록[이름] = 위치
        환율들.append({
            "이름": 짧은,
            "짧은이름": 짧은,
            "표시가": FX.금액표시(현재가, cur["unit"]),
            "위치": 위치,
            "이전위치": 최근_위치(스냅샷들, 이름, 오늘날짜),
            "하루변화": 변화글,
            # ★ 토·일·월 아침에는 금요일 등락이 같은 값으로 세 번 '어제' 로
            #   나갔습니다. 마지막 자료가 어제가 아니면 그 날짜를 적습니다.
            "변화라벨": ("어제" if 묵음 <= 1 else
                      f"{자료.index.max().month}/{자료.index.max().day} 종가"),
            "체감": FX.체감_환산(현재가, cur),
            "구간일수": 구간_머문날수(스냅샷들, 이름, 오늘날짜, 위치),
            "묵음": 묵음,
        })
    알림글(f"   환율 {len(환율들)}종" + (f" / 못 받음: {', '.join(빠진통화)}"
                                  if 빠진통화 else ""))

    # ---- 원달러 · 시세 ----
    # ★ 원달러를 못 받으면 예전에는 말없이 1,390원(고정값)으로 계산했습니다.
    #   메시지 환율 블록(다른 경로)과도 어긋났습니다. 이제는 환율 블록의
    #   달러 → 어제 기록의 환율 → 고정값 순으로 쓰고, 고정값까지 가면
    #   '믿을 수 없는 날' 로 표시합니다.
    환율대체 = False
    try:
        원달러 = PF.환율_조회()
    except Exception as e:                                   # noqa: BLE001
        if 달러현재가:
            원달러 = 달러현재가
            알림글(f"   원달러 조회 실패({e}) — 환율 블록의 {원달러:,.0f}원 사용")
        elif PF._숫자(어제.get("환율")) > 0:
            원달러 = PF._숫자(어제["환율"])
            경고글(f"원달러 조회 실패({e}) — 어제 기록의 {원달러:,.0f}원 사용")
        else:
            원달러, 환율대체 = PF.기본환율, True
            경고글(f"원달러 조회 실패({e}) — 고정값 {원달러:,.0f}원 사용")
    시세맵, 시세실패 = PF.시세_모으기(종목들)
    알림글(f"   시세 {len(시세맵)}건" + (f" / 실패 {len(시세실패)}건"
                                  if 시세실패 else ""))
    for 티커, 말 in 시세실패[:5]:
        알림글(f"     x {티커}: {말}")

    오늘 = PF.현황_스냅샷(종목들, 원달러, 시세맵, 날짜=오늘날짜)
    오늘["환율위치"] = 위치기록
    if 환율대체:
        오늘["환율대체"] = True
    알림글(f"   총액 {PF.금액_한글(오늘['총액'])}")

    # ---- 목표 비중 · 리밸런싱 신호 ----
    목표 = 자산.get("목표") or {}
    기준 = 자산.get("목표기준") or PF.목표기준_추측(목표)
    # 앱과 같은 규칙: 저장값 중 지금 보유 계좌만, 없으면 공용 기본값
    조정계좌 = PF.조정계좌_정하기(자산.get("조정계좌"), 종목들)
    신호 = PF.리밸런싱_신호(종목들, 목표, 기준, 조정계좌,
                     임계=BR.기본_임계["리밸런싱_괴리"],
                     환율=원달러, 시세맵=시세맵)
    if 신호:
        기준 = 신호[0].get("기준") or 기준
    if 목표:
        알림글(f"   목표({기준}) 기준 신호 {len(신호)}건 · "
              f"범위 {', '.join(조정계좌)}")

    # 계좌 블록은 시장(US/KR/COIN), 신호는 자산군으로 셉니다. 국내 상장
    # 해외 ETF 는 두 곳에서 다르게 잡히므로 그 액수를 미리 뽑아 둡니다.
    # 자산군 기준일 때만 해당합니다. 시장 기준이면 그 ETF 는 여기서도 KR 입니다.
    엇갈린해외 = (PF.엇갈린_해외(종목들, 조정계좌, 원달러, 시세맵)
             if 신호 and 기준 == "자산군" else 0.0)

    # ---- 숫자 점검 — 오늘 값을 믿을 수 있나 ----
    탈, 믿음 = 숫자_점검(오늘, 어제, 환율들, 빠진통화, 종목들)
    기록실패 = 담긴것.get("_기록실패")
    if 기록실패:
        탈.append("지난 기록을 읽지 못해 오늘은 비교 없이 보냅니다")
        경고글(f"기록 파일을 읽지 못했습니다: {기록실패}")
    for 설명 in 탈:
        경고글(f"숫자 점검: {설명}")

    # ---- 글 만들기 ----
    최고, 최고날 = 최고_기록(기록, 스냅샷들, 오늘날짜)
    if 믿음:
        묶음 = {
            "오늘": 오늘,
            "어제": 어제,
            "주초": 주초것(스냅샷들, 오늘날짜),
            "월초": 월초것(스냅샷들, 오늘날짜),
            "지난달": 지난달것(스냅샷들, 오늘날짜),
            "연초": 연초것(스냅샷들, 오늘날짜),
            "최고": 최고, "최고날": 최고날,
            "기여": PF.기여도(오늘, 어제),
        }
    else:
        # ★ 믿을 수 없는 날은 비교를 통째로 뺍니다. 틀린 총액으로 '하루 만에
        #   -40%', '역대 최고' 를 말하느니 오늘 숫자만 보이고 아래에 이유를
        #   적습니다.
        묶음 = {"오늘": 오늘}
    묶음.update({"신호": 신호, "엇갈린해외": 엇갈린해외})
    본문, 모드 = BR.브리핑_만들기(
        묶음, 환율들, 오늘날짜,
        신호범위=f"{'·'.join(조정계좌)} 계좌 · {기준} 기준" if 신호 else "")

    # ★ 숨기지 않고 메시지에 붙입니다. 로그에만 남기면 아무도 안 봅니다.
    if 탈:
        본문 += ("\n\n⚠️ <b>숫자 점검에 걸린 것</b>\n"
              + "\n".join(f"　· {BR._안전(x)}" for x in 탈)
              + ("\n　오늘은 어제와 비교하지 않았고 기록도 남기지 않습니다"
                 if not 믿음 else ""))

    본문 += "\n\n🤖 자동 발송"
    알림글(f"   모드: {모드}")

    if 시험만:
        알림글("")
        알림글(본문)
        알림글("")
        알림글("   DRY_RUN — 보내지 않았습니다.")
        return 0

    # ---- 기록 먼저, 전송은 그다음 ----
    # ★ 예전에는 보낸 뒤에 기록했습니다. 그러면 Gist 저장이 실패한 날
    #   '보냈다' 는 사실이 사라져서, 20분·40분 뒤 예약이 같은 브리핑을
    #   또 보내고 거짓 🚨 실패 알림까지 세 번 갔습니다.
    #   이제는 '오늘 보냄' 과 오늘 스냅샷을 먼저 남기고 보냅니다.
    #   · 기록이 안 되면 → 보내지 않고 실패 (다음 예약이 다시 해 봄)
    #   · 전송이 확실히 실패하면 → 기록을 되돌리고 실패 (다음 예약이 다시)
    #   · 보냈는지 모르면(응답 시간 초과) → 기록을 그대로 둠. 두 통 가는
    #     것보다 한 통 놓치는 쪽이 낫고, 경고로 남겨 알 수 있게 합니다.
    if 기록실패:
        # ★ 기록 파일을 못 읽은 날 그걸 덮어쓰면 쌓아 온 기록이 사라집니다.
        #   '오늘 보냄' 만 작은 상태 파일에 따로 남깁니다.
        쓸파일, 원래기록 = 상태파일, dict(담긴것.get(상태파일) or {})
        새것 = {**원래기록, "마지막발송일": 오늘날짜}
    else:
        쓸파일 = 기록파일
        원래기록 = json.loads(json.dumps(기록, default=str))
        남길것 = [s for s in 스냅샷들 if str(s.get("날짜")) != 오늘날짜]
        if 믿음:
            남길것.append(오늘)
        새것 = dict(기록)
        새것["스냅샷"] = 기록_다듬기(남길것, 오늘날짜)
        새것["마지막발송일"] = 오늘날짜
        if 믿음 and PF._숫자(오늘.get("총액")) > 최고:
            새것["최고"] = {"총액": 오늘["총액"], "날짜": 오늘날짜}
        elif 최고 > 0:
            새것["최고"] = {"총액": 최고, "날짜": 최고날}
    좋음, 오류 = gist_쓰기(깃토큰, 기스트, 쓸파일, 새것)
    if not 좋음:
        오류글(f"{오류} — 기록을 못 남겨서 보내지 않았습니다 "
             "(보내면 다음 예약이 또 보냅니다). 다음 예약이 다시 시도합니다.")
        return 1
    알림글(f"   기록 저장 완료 ({쓸파일})")

    상태, 말 = TG.보내기(텔레토큰, 텔레방, 본문)
    if 상태 == "보냄":
        알림글("   전송 완료")
        return 0
    if 상태 == "모름":
        경고글(f"텔레그램 전송 결과를 모릅니다: {말} — 중복을 피하려고 "
             "다시 보내지 않습니다. 텔레그램에 안 왔으면 Run workflow 로 "
             "다시 보내세요.")
        return 0
    되돌림, 되돌림오류 = gist_쓰기(깃토큰, 기스트, 쓸파일, 원래기록)
    if 되돌림:
        오류글(f"텔레그램 전송 실패: {말} (기록을 되돌렸으니 다음 예약이 "
             "다시 보냅니다)")
    else:
        오류글(f"텔레그램 전송 실패: {말} — 기록도 되돌리지 못해 오늘은 더 "
             f"시도하지 않습니다({되돌림오류}). Run workflow 로 보내세요.")
    return 1


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
