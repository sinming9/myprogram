"""
==========================================================================
환율 매일 요약  (GitHub Actions 에서 실행)
==========================================================================
매일 정해진 시간에 5개 통화(달러·엔·유로·위안·싱가포르 달러)의 어제·지난주
대비, 그리고 1개월~3년 평균 대비를 한 번에 텔레그램으로 보냅니다.

호텔 가격 알림과 달리 **Gist 도, RapidAPI 키도 필요 없습니다.** 환율은
공개 데이터(FinanceDataReader/stooq)라서 매번 새로 계산하면 되고, "이전과
비교해서 알릴지 말지" 를 판단할 필요 없이 매일 그대로 보내는 요약이기
때문입니다.

--------------------------------------------------------------------------
필요한 환경변수 (GitHub → Settings → Secrets and variables → Actions)
--------------------------------------------------------------------------
  TELEGRAM_TOKEN      봇 토큰      (필수 — 호텔 알림과 같은 값을 씁니다)
  TELEGRAM_CHAT_ID    대화방 id    (필수 — 위와 동일)

  DRY_RUN=1           계산만 하고 보내지 않습니다 (시험용)

--------------------------------------------------------------------------
직접 돌려 보기
--------------------------------------------------------------------------
  Windows :  set TELEGRAM_TOKEN=...  &&  py -3 scripts\\fx_check.py
  그 외    :  TELEGRAM_TOKEN=... python3 scripts/fx_check.py
==========================================================================
"""

import os
import sys
from datetime import datetime

# engines/ 를 찾을 수 있게 저장소 뿌리를 경로에 넣습니다
뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)

from engines import fx as FX  # noqa: E402
from engines import hotel as HT  # noqa: E402
#  ★ 텔레그램 전송 함수는 engines/hotel.py 에 있습니다. 호텔에만 쓰는
#    내용이 아니라 일반적인 HTTP 요청이라서 그대로 가져다 씁니다.
#    새로 똑같은 코드를 만들지 않습니다.


def _출력_준비():
    for 흐름 in (sys.stdout, sys.stderr):
        try:
            흐름.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def 알림글(*조각):
    print(*조각, flush=True)


def 환경(이름, 기본=""):
    return (os.environ.get(이름, "") or "").strip() or 기본


def 실행() -> int:
    _출력_준비()
    시험만 = 환경("DRY_RUN") in ("1", "true", "TRUE", "yes")

    텔레토큰 = 환경("TELEGRAM_TOKEN")
    텔레방 = 환경("TELEGRAM_CHAT_ID")
    if not 텔레토큰 or not 텔레방:
        알림글("!! TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 가 없습니다.")
        알림글("   GitHub 저장소 → Settings → Secrets and variables → Actions "
              "에서 추가하세요. (호텔 알림에 넣은 값과 같은 것이면 됩니다)")
        return 1

    알림글(f"== 환율 매일 요약 {datetime.now():%Y-%m-%d %H:%M} ==")
    if 시험만:
        알림글("   DRY_RUN — 계산만 하고 보내지 않습니다")

    본문, 실패목록 = FX.텔레그램_전체요약()

    for 이름 in FX.CURRENCIES:
        상태 = "실패" if 이름 in dict(실패목록) else "성공"
        알림글(f"   {'x' if 상태 == '실패' else 'o'} {이름}: {상태}"
              + (f" — {dict(실패목록)[이름]}" if 상태 == "실패" else ""))

    if 시험만:
        알림글("")
        알림글(본문)
        알림글("")
        알림글("   DRY_RUN — 보내지 않았습니다.")
        return 0

    좋음, 말 = HT.텔레그램_보내기(텔레토큰, 텔레방, 본문)
    if not 좋음:
        알림글(f"!! 전송 실패: {말}")
        return 1

    알림글(f"   전송 완료 (실패 통화 {len(실패목록)}개)")

    # 전부 실패했으면(즉 아무 통화도 못 가져왔으면) 빨간불을 켭니다.
    # 몇 개만 실패한 건 그날의 데이터 사정일 수 있어 정상 종료로 둡니다.
    if len(실패목록) >= len(FX.CURRENCIES):
        알림글("!! 모든 통화를 못 가져왔습니다.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(실행())
    except KeyboardInterrupt:
        sys.exit(130)
