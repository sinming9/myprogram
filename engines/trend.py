"""
==========================================================================
자산 추이 — 1일·1주·1달·1분기·1년·10년
==========================================================================
아침 브리핑이 매일 Gist(portfolio_history.json)에 남기는 기록으로
'총 평가액 / 총 매입액(원금) / 수익률' 의 흐름을 만듭니다. 구글 시트에
손으로 남기던 '날짜 · 총 매입 · 총 평가 · 수익률' 표와 같은 내용입니다.

[이 파일은 streamlit 을 쓰지 않습니다]
  앱(자산배분 → 추이 탭)과 GitHub Actions(텔레그램 그래프)가 같이 씁니다.
  그래서 두 곳의 숫자가 항상 같습니다.

[수익률을 어떻게 셈하나]
  (원금 있는 총액 − 원금) ÷ 원금. 평균단가 없이 평가액만 넣은 예금·펀드는
  원금을 모르므로 빼고 셉니다(빼지 않으면 수익률이 수백 % 로 부풉니다).
  옛 기록에 '원금있는총액' 이 없으면 총액으로 셉니다.
==========================================================================
"""

from datetime import date, timedelta

# (이름, 며칠 전부터)  — 1일은 '어제와 오늘' 두 점입니다
기간들 = [
    ("1일", 1), ("1주", 7), ("1달", 30), ("1분기", 91),
    ("1년", 365), ("10년", 3650),
]


def _숫자(값) -> float:
    try:
        v = float(값)
        return v if v == v else 0.0
    except (TypeError, ValueError):
        return 0.0


def 점들(스냅샷들) -> list:
    """[{날짜(date), 평가액, 원금, 수익률}] 날짜 오름차순. 비거나 깨진 기록은 뺍니다."""
    결과 = {}
    for s in 스냅샷들 or []:
        if not isinstance(s, dict):
            continue
        try:
            d = date.fromisoformat(str(s.get("날짜"))[:10])
        except ValueError:
            continue
        총액 = _숫자(s.get("총액"))
        if 총액 <= 0:
            continue
        원금 = _숫자(s.get("원금"))
        기준 = _숫자(s.get("원금있는총액")) if "원금있는총액" in s else 총액
        수익률 = ((기준 - 원금) / 원금 * 100) if 원금 > 0 else None
        결과[d] = {"날짜": d, "평가액": 총액, "원금": 원금, "수익률": 수익률}
    return [결과[d] for d in sorted(결과)]


def 구간(모든점: list, 일수: int, 오늘: date = None) -> list:
    """최근 '일수' 안의 점들. 구간 시작 바로 앞의 점도 넣어 비교 기준으로 씁니다.

    ★ 1주를 '7일 안의 점' 만으로 자르면, 기록이 하루라도 빠진 주에는 첫 점이
      6일 전이 되어 '이번 주 변화' 가 하루치 모자랍니다. 시작 직전 점을
      기준으로 넣어야 시트의 '일주일 전 대비' 와 같은 뜻이 됩니다.
    """
    if not 모든점:
        return []
    오늘 = 오늘 or 모든점[-1]["날짜"]
    시작 = 오늘 - timedelta(days=일수)
    안쪽 = [p for p in 모든점 if 시작 < p["날짜"] <= 오늘]
    앞 = [p for p in 모든점 if p["날짜"] <= 시작]
    if 앞:
        안쪽.insert(0, 앞[-1])
    return 안쪽


def 요약(구간점: list) -> dict:
    """구간의 처음과 끝 비교. 점이 둘 미만이면 빈 dict."""
    if len(구간점) < 2:
        return {}
    처음, 끝 = 구간점[0], 구간점[-1]
    평가차 = 끝["평가액"] - 처음["평가액"]
    원금차 = 끝["원금"] - 처음["원금"]
    return {
        "시작": 처음["날짜"], "끝": 끝["날짜"],
        "평가액": 끝["평가액"], "평가차": 평가차,
        "평가차율": (평가차 / 처음["평가액"] * 100) if 처음["평가액"] else 0.0,
        "원금": 끝["원금"], "원금차": 원금차,
        # 평가액 변화에서 '내가 넣은 돈' 을 빼면 시장이 준 것
        "시장분": 평가차 - 원금차,
        "수익률": 끝["수익률"],
        "수익률차": (None if 끝["수익률"] is None or 처음["수익률"] is None
                  else 끝["수익률"] - 처음["수익률"]),
        "최고": max(p["평가액"] for p in 구간점),
        "최저": min(p["평가액"] for p in 구간점),
    }


def 그림_만들기(구간점: list, 제목: str = "") -> bytes:
    """텔레그램에 보낼 PNG. matplotlib 이 없거나 점이 모자라면 b"".

    ★ 그래프에 한글을 쓰려면 한글 글꼴이 있어야 합니다. GitHub 러너에는
      워크플로가 나눔 글꼴을 깔아 줍니다. 글꼴이 없는 곳(예: 이 PC 에 없을
      때)에서는 글자가 네모로 깨지므로, 그때는 영어 라벨로 그립니다.
    """
    if len(구간점) < 2:
        return b""
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return b""

    한글됨 = False
    for 이름 in ("NanumGothic", "Malgun Gothic", "AppleGothic", "Noto Sans CJK KR"):
        if any(f.name == 이름 for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = 이름
            한글됨 = True
            break
    plt.rcParams["axes.unicode_minus"] = False
    글 = (lambda 한, 영: 한) if 한글됨 else (lambda 한, 영: 영)

    x = [p["날짜"] for p in 구간점]
    평가 = [p["평가액"] / 1e4 for p in 구간점]          # 만원 단위
    원금 = [p["원금"] / 1e4 for p in 구간점]
    수익 = [p["수익률"] for p in 구간점]

    그림, (위, 아래) = plt.subplots(
        2, 1, figsize=(8, 5.2), dpi=130, sharex=True,
        gridspec_kw={"height_ratios": [2.3, 1]})
    위.plot(x, 평가, color="#2B6ED5", lw=2.2, label=글("총 평가액", "Value"))
    위.fill_between(x, 평가, min(평가 + 원금), color="#2B6ED5", alpha=.08)
    위.plot(x, 원금, color="#8E8E8E", lw=1.4, ls=":", label=글("총 매입액", "Cost"))
    위.legend(loc="upper left", frameon=False, fontsize=9)
    위.set_ylabel(글("만원", "10k KRW"), fontsize=9)
    위.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v:,.0f}"))
    if 제목:
        위.set_title(제목 if 한글됨 else "Portfolio", fontsize=11, loc="left")

    if any(v is not None for v in 수익):
        아래.plot([d for d, v in zip(x, 수익) if v is not None],
                 [v for v in 수익 if v is not None], color="#18A57A", lw=1.8)
        아래.axhline(0, color="#999", lw=.8)
        아래.set_ylabel(글("수익률 %", "Return %"), fontsize=9)

    for 축 in (위, 아래):
        축.grid(alpha=.25)
        for 변 in ("top", "right"):
            축.spines[변].set_visible(False)
    아래.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    그림.autofmt_xdate()
    그림.tight_layout()
    버퍼 = io.BytesIO()
    그림.savefig(버퍼, format="png")
    plt.close(그림)
    return 버퍼.getvalue()


def 기록_일수(모든점: list) -> int:
    """첫 기록부터 마지막 기록까지 며칠인지 (긴 기간 버튼 안내용)."""
    if len(모든점) < 2:
        return 0
    return (모든점[-1]["날짜"] - 모든점[0]["날짜"]).days
