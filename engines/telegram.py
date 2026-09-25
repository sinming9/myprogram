"""
==========================================================================
텔레그램 보내기
==========================================================================
[왜 따로 떼었나]
  원래 engines/hotel.py 안에 있었는데, 호텔 기능을 접기로 하면서 아침
  브리핑과 환전 타이밍 페이지가 호텔 모듈에 매달린 꼴이 됐습니다.
  보내는 일만 하는 작은 모듈로 옮겼습니다.

[결과가 세 가지인 이유]  "보냄" / "실패" / "모름"
  보냈는지 **확실히 모르는** 경우가 있습니다. 요청은 텔레그램에 닿았는데
  응답을 읽다가 시간이 초과되면, 메시지는 이미 도착했을 수 있습니다.
  이걸 '실패' 로 치면 다음 예약이 같은 브리핑을 또 보내고, 거짓 🚨 실패
  알림까지 갑니다(감사에서 실제로 걸린 경로). 그래서 따로 둡니다.

[다시 시도하는 경우]
  · 429 (너무 자주 보냄) — 텔레그램이 알려 준 초만큼 기다렸다가
  · 5xx / 연결 자체가 안 됨 — 잠깐 기다렸다가
  메시지가 닿지 않은 게 확실할 때만 다시 보냅니다. 두 번 가는 것보다
  한 번 늦게 가는 편이 낫습니다.
==========================================================================
"""

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

최대_길이 = 4096          # 텔레그램 한 통의 글자 수 한도


def 보내기(토큰, 채팅id, 글, 시간제한=20, 시도=3, 잠=time.sleep) -> tuple:
    """(상태, 설명). 상태 = "보냄" / "실패" / "모름"."""
    if not 토큰 or not 채팅id:
        return "실패", "텔레그램 토큰 또는 chat_id 가 없습니다."
    글 = str(글)
    if len(글) > 최대_길이:
        # 잘려서라도 가는 게 400 으로 통째로 안 가는 것보다 낫습니다
        글 = 글[:최대_길이 - 40] + "\n\n… (길어서 뒷부분을 줄였습니다)"
    주소 = f"https://api.telegram.org/bot{str(토큰).strip()}/sendMessage"
    본문 = urllib.parse.urlencode({
        "chat_id": str(채팅id).strip(),
        "text": 글,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    마지막 = ""
    for 회차 in range(1, 시도 + 1):
        req = urllib.request.Request(주소, data=본문, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=시간제한) as resp:
                결과 = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            설명, 기다림 = _http_오류(e)
            if 기다림 is None:                  # 다시 해도 안 되는 오류
                return "실패", 설명
            마지막 = 설명
        except (socket.timeout, TimeoutError) as e:
            return "모름", f"응답을 기다리다 시간이 초과됐습니다({e}). " \
                          "메시지는 도착했을 수 있습니다."
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                return "모름", f"응답을 기다리다 시간이 초과됐습니다({e.reason})."
            마지막, 기다림 = f"연결하지 못했습니다: {e.reason}", 3 * 회차
        except Exception as e:                               # noqa: BLE001
            return "실패", f"보내지 못했습니다: {type(e).__name__}: {e}"
        else:
            if 결과.get("ok"):
                return "보냄", "보냈습니다."
            return "실패", str(결과.get("description") or "알 수 없는 오류")
        if 회차 < 시도:
            잠(min(기다림, 30))
    return "실패", f"{시도}번 시도했지만 보내지 못했습니다. {마지막}".strip()


def _http_오류(e) -> tuple:
    """(설명, 기다릴 초). 기다릴 초가 None 이면 다시 해도 소용없는 오류."""
    속, 기다림 = "", None
    try:
        자료 = json.loads(e.read().decode("utf-8", "replace"))
        속 = 자료.get("description", "")
        기다림 = (자료.get("parameters") or {}).get("retry_after")
    except Exception:                                        # noqa: BLE001
        pass
    if e.code == 429:
        return f"텔레그램 429 (너무 자주 보냄). {속}".strip(), int(기다림 or 5)
    if e.code >= 500:
        return f"텔레그램 서버 오류 {e.code}. {속}".strip(), 5
    # ★ 400 은 원인이 여러 가지입니다(HTML 태그 오류, 길이 초과, chat_id).
    #   예전에는 무조건 "chat_id 확인" 을 붙여서 엉뚱한 곳을 보게 했습니다.
    안내 = ""
    if e.code == 401:
        안내 = "봇 토큰이 잘못되었습니다."
    elif e.code == 403:
        안내 = "봇이 차단되었습니다. 대화방에서 봇을 다시 허용하세요."
    elif e.code == 400 and "chat not found" in 속.lower():
        안내 = "chat_id 가 잘못되었거나, 봇에게 먼저 /start 를 누르지 않았습니다."
    elif e.code == 400 and "parse" in 속.lower():
        안내 = "메시지의 HTML 모양이 잘못되었습니다(프로그램 쪽 문제)."
    return f"텔레그램 응답 {e.code}. {안내} {속}".strip(), None


def 텔레그램_보내기(토큰, 채팅id, 글, 시간제한=20) -> tuple:
    """(성공, 메시지) — 예전 모양을 그대로 쓰는 곳을 위한 얇은 포장.

    '모름' 은 성공으로 칩니다. 화면에서 누른 시험 전송이라면 사람이
    텔레그램을 보고 판단할 수 있고, 다시 누르게 만들면 두 통이 갑니다.
    """
    상태, 말 = 보내기(토큰, 채팅id, 글, 시간제한)
    return 상태 != "실패", 말
