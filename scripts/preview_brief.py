"""
==========================================================================
아침 브리핑 미리보기 — 지난 날짜의 판을 **보내지 않고** 화면에만 찍습니다
==========================================================================
  python scripts/preview_brief.py 2026-11-07 2026-11-08

[무엇으로 만드나]
  Gist 에서 내려받아 data/ 에 둔 세 파일을 읽습니다 (Gist 는 건드리지 않음).
    data/portfolio_history.json   그날의 스냅샷 (총액·계좌·종목별 금액)
    data/portfolio.json           종목 목록·목표 비중
    data/networth.json            외화 보유·여행 환전 (없어도 됨)
  글 조립은 러너(scripts/morning_brief.py)와 **같은 함수**를 씁니다.

[실제 발송분과 다를 수 있는 곳]
  · 시세는 다시 받지 않고 그날 스냅샷에 남은 금액을 씁니다.
  · 환율은 지금 야후에서 받은 일봉을 그 날짜까지만 잘라 쓰고, '그날 아침에
    받았던 값' 은 스냅샷에서 되살립니다(달러 = 기록의 환율, 엔·싱달 = 외화
    평가액 ÷ 수량). 여러 날짜를 주면 앞 날짜의 값을 뒤 날짜가 이어받습니다
    — 주말에 환율이 그대로인지 확인하는 용도입니다.
  · 종목 수량·목표 비중은 지금 저장된 portfolio.json 기준입니다(수량은
    그날 스냅샷에 있으면 그 값).
텔레그램 전송·Gist 저장 코드는 아예 부르지 않습니다.
==========================================================================
"""

import copy
import html
import json
import os
import re
import sys

뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)
sys.path.insert(0, os.path.join(뿌리, "scripts"))

import pandas as pd  # noqa: E402

import morning_brief as MB  # noqa: E402
from engines import brief as BR  # noqa: E402
from engines import fx as FX  # noqa: E402
from engines import portfolio as PF  # noqa: E402


def _읽기(폴더, 이름, 필수=True):
    경로 = os.path.join(폴더, 이름)
    if not os.path.exists(경로):
        if 필수:
            sys.exit(f"{경로} 이 없습니다 — Gist 에서 내려받아 넣어 주세요.")
        return {}
    with open(경로, encoding="utf-8") as f:
        return json.load(f)


def _외화_빼기(스냅):
    """스냅샷에서 '외화' 계좌 몫을 덜어냅니다 (새 환율 기준값으로 다시 더하려고)."""
    for 열쇠, 칸 in list((스냅.get("종목") or {}).items()):
        if 칸.get("계좌") != "외화":
            continue
        금액, 원금 = PF._숫자(칸.get("금액")), PF._숫자(칸.get("원금"))
        스냅["총액"] = PF._숫자(스냅.get("총액")) - 금액
        스냅["원금"] = PF._숫자(스냅.get("원금")) - 원금
        if 원금 > 0:
            스냅["원금있는총액"] = PF._숫자(스냅.get("원금있는총액")) - 금액
        del 스냅["종목"][열쇠]
    for 칸 in ("계좌", "계좌시장", "자산군"):
        (스냅.get(칸) or {}).pop("외화", None)


def _그날_행과_시세(종목들, 스냅):
    """그날 스냅샷의 금액·수량으로 (종목 행, 시세맵) 을 되살립니다."""
    환율 = PF._숫자(스냅.get("환율")) or PF.기본환율
    칸들 = 스냅.get("종목") or {}

    def 열쇠(r):
        티커, _ = PF._시세열쇠(r)
        계좌 = str(r.get("계좌") or "기타").strip() or "기타"
        이름 = str(r.get("이름") or 티커 or "이름없음").strip()
        return f"{계좌}|{티커 or 이름}"

    개수 = {}
    for r in 종목들:
        개수[열쇠(r)] = 개수.get(열쇠(r), 0) + 1
    행들, 시세맵 = [], {}
    for r in 종목들:
        r = dict(r)
        칸 = 칸들.get(열쇠(r))
        if 칸 and 개수[열쇠(r)] == 1:
            금액, 수량 = PF._숫자(칸.get("금액")), PF._숫자(칸.get("수량"))
            티커, 시장 = PF._시세열쇠(r)
            if r.get("평가액(직접입력)"):
                r["평가액(직접입력)"] = 금액 / (환율 if 시장 == "US" else 1)
            elif 수량 > 0:
                r["수량"] = 수량
                값 = 금액 / 수량
                시세맵[(티커, 시장)] = (
                    {"현재가": 값 / 환율, "통화": "USD"} if 시장 == "US" else
                    {"현재가": 값, "통화": "KRW", "원화표시": True})
        행들.append(r)
    return 행들, 시세맵


def 미리보기(날짜, 전체, 기록, 자산, 순자산, 실제환율) -> str:
    원본 = next((s for s in 전체 if str(s.get("날짜")) == 날짜), None)
    if not 원본:
        return f"{날짜}: 기록에 그날 스냅샷이 없습니다"
    if "종목" not in 원본:
        return f"{날짜}: 종목별 칸이 지워진 오래된 기록이라 다시 만들 수 없습니다"
    오늘 = copy.deepcopy(원본)
    스냅샷들 = [s for s in 전체 if str(s.get("날짜")) < 날짜]
    어제 = MB.어제것(스냅샷들, 날짜)
    종목들 = [r for r in (자산.get("종목") or []) if isinstance(r, dict)]

    외화출처 = 순자산 if ("외화" in 순자산 or "여행" in 순자산) else 자산
    외화입력 = [r for r in (외화출처.get("외화") or []) if isinstance(r, dict)
            and str(r.get("통화") or "").strip() and PF._숫자(r.get("보유수량")) > 0]
    여행입력 = [r for r in (외화출처.get("여행") or []) if isinstance(r, dict)
            and r.get("사용", True) is not False and str(r.get("통화") or "").strip()]
    여행_포함 = bool(외화출처.get("여행_순자산포함"))
    필요통화 = {str(r["통화"]).strip().upper() for r in 외화입력 + 여행입력}

    # 그날 아침에 받았던 환율 — 스냅샷에서 되살립니다 (화면 단위: 엔은 100엔당)
    아침값 = {"USD": PF._숫자(원본.get("환율")) or None}
    for 열쇠, 칸 in (원본.get("종목") or {}).items():
        금액, 수량 = PF._숫자(칸.get("금액")), PF._숫자(칸.get("수량"))
        if 칸.get("계좌") != "외화" or 수량 <= 0:
            continue
        코드 = 열쇠.split("|", 1)[1]
        if 코드.startswith("여행:"):
            코드 = next((str(r["통화"]).strip().upper() for r in 여행입력
                       if str(r.get("여행명")) == 코드[3:]), "")
        배수 = next((c["scale"] for 이, c in FX.CURRENCIES.items()
                   if MB.통화코드(이) == 코드), 1)
        if 코드:
            아침값.setdefault(코드, 금액 / 수량 * 배수)

    def 가져오기(cur, years=3):
        이름 = next(이 for 이, c in FX.CURRENCIES.items() if c is cur)
        if 이름 not in 실제환율:
            실제환율[이름] = FX.환율_가져오기(cur, years=years)
        자료, 출처, 시도 = 실제환율[이름]
        자료 = 자료[자료.index < pd.Timestamp(날짜)].copy()
        값 = 아침값.get(MB.통화코드(이름))
        if 값:
            자료.iloc[-1, 자료.columns.get_loc("Close")] = 값
            출처 += " · 그날 아침 값은 기록에서 복원"
        return 자료, 출처, 시도

    print(f"== 미리보기 {날짜} (보내지 않음 · 저장하지 않음) ==")
    모음 = MB.환율_모으기(스냅샷들, 날짜, 필요통화, 가져오기)
    환율표 = 모음["환율표"]
    원달러 = 모음["달러현재가"] or PF._숫자(오늘.get("환율")) or PF.기본환율
    print(f"   원달러 {원달러:,.2f}원 (미국 종목 환산) · 기록의 환율 {PF._숫자(원본.get('환율')):,.2f}원")
    print("   시세 기준일: " + (json.dumps(오늘["시세기준일"], ensure_ascii=False)
                           if 오늘.get("시세기준일")
                           else "기록에 없음 (이번 수정 전에 남긴 기록)"))

    # 외화·여행 환전을 새 기준값으로 다시 평가해 더합니다 (러너와 같은 순서)
    _외화_빼기(오늘)
    외화들 = MB.외화_평가(외화입력, 환율표)
    여행들 = MB.여행_평가(여행입력, 환율표)
    더할것 = [(f"외화|{x['코드']}", x["짧은이름"], x["평가액"], x["원금"], x["수량"])
            for x in 외화들]
    if 여행_포함:
        더할것 += [(f"외화|여행:{t['이름']}", f"{t['이름']} 환전", t["평가액"],
                 t["원금"], t["모음"]) for t in 여행들 if t["평가액"] > 0]
    for 열쇠, 이름, 평가, 원금, 수량 in 더할것:
        MB.오늘_더하기(오늘, 열쇠, 이름, 평가, 원금, 수량)
    오늘["환율위치"] = 모음["위치기록"]
    오늘["환율값"] = 모음["값기록"]

    행들, 시세맵 = _그날_행과_시세(종목들, 원본)
    목표 = 자산.get("목표") or dict(BR.기본_목표비중)
    기준 = 자산.get("목표기준") or PF.목표기준_추측(목표)
    그날환율 = PF._숫자(원본.get("환율")) or 원달러
    리밸런싱 = PF.리밸런싱_신호(행들, 목표, 기준, BR.리밸런싱_계좌, 임계=0,
                       환율=그날환율, 시세맵=시세맵)
    if 리밸런싱:
        기준 = 리밸런싱[0].get("기준") or 기준

    자료 = MB.자료_만들기(오늘, 어제, 스냅샷들, 기록, 날짜, 모음["환율들"], 외화들,
                     여행들, 리밸런싱, 행들, 그날환율, 시세맵, 기준,
                     신규투입=자산.get("신규투입"))
    본문, 모드 = BR.브리핑_만들기(자료, 날짜)
    본문 += "\n\n🤖 자동 발송"
    print(f"   모드: {모드}\n")

    # 뒤 날짜가 이 날짜의 환율 기준값·외화 평가를 이어받도록 바꿔 둡니다
    전체[전체.index(원본)] = 오늘
    return html.unescape(re.sub(r"</?b>", "", 본문))


def main():
    for 흐름 in (sys.stdout, sys.stderr):
        try:
            흐름.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    날짜들 = sorted(a for a in sys.argv[1:] if not a.startswith("--"))
    if not 날짜들:
        sys.exit("쓰는 법: python scripts/preview_brief.py 2026-11-07 2026-11-08")
    폴더 = os.path.join(뿌리, "data")
    기록 = _읽기(폴더, MB.기록파일)
    자산 = _읽기(폴더, MB.자산파일)
    순자산 = _읽기(폴더, MB.순자산파일, 필수=False)
    전체 = copy.deepcopy(PF.기록_정렬(기록))
    실제환율 = {}
    for 날짜 in 날짜들:
        글 = 미리보기(날짜, 전체, 기록, 자산, 순자산, 실제환율)
        print("─" * 60)
        print(글)
        print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
