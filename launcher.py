"""
==========================================================================
개인 대시보드 실행 도우미
==========================================================================
실행_윈도우.bat 이 이 파일을 실행합니다. 직접 실행해도 됩니다.

    python launcher.py

배치 파일(.bat)에 한글을 넣으면 Windows cmd 가 인코딩을 잘못 읽어서
명령이 깨지기 때문에, 한글 안내와 실제 작업은 모두 이 파이썬 파일에서 합니다.
==========================================================================
"""

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

앱_폴더 = os.path.dirname(os.path.abspath(__file__))
필수_패키지 = ["streamlit", "pandas", "plotly"]
포트 = 8501


def 포트_열렸나(포트번호, 시간제한=0.5):
    try:
        with socket.create_connection(("127.0.0.1", 포트번호), timeout=시간제한):
            return True
    except OSError:
        return False


def 빈_포트_찾기(시작, 개수=20):
    for p in range(시작, 시작 + 개수):
        if not 포트_열렸나(p):
            return p
    return None


def 이미_실행중_처리():
    """8501 이 이미 쓰이는 중일 때. 계속 진행하면 True, 끝내려면 False."""
    global 포트
    줄()
    print(f"  [주의] {포트} 번 포트에 이미 서버가 돌고 있습니다.")
    줄()
    print()
    print("  프로그램 파일을 방금 새로 받으셨다면, 그 서버는 '예전 코드'로")
    print("  돌아가고 있을 가능성이 큽니다.")
    print()
    print("  Streamlit 은 pages/ 안의 화면 파일만 매번 다시 읽고,")
    print("  storage.py · ui.py 같은 공용 파일은 서버를 처음 켤 때 읽은 것을")
    print("  계속 씁니다. 그래서 파일만 바꾸고 서버를 안 껐다 켜면")
    print("  아래 같은 오류가 납니다.")
    print()
    print("      AttributeError: module 'storage' has no attribute '...'")
    print()
    print("  ▶ 가장 확실한 해결: 열려 있는 검은 창을 전부 닫고 다시 실행")
    print("     (안 닫히면 명령 프롬프트에서:  taskkill /f /im python.exe )")
    print()
    줄("-")
    새포트 = 빈_포트_찾기(포트 + 1)
    print("  1) 그래도 새로 실행 " + (f"(포트 {새포트} 사용)" if 새포트 else "") + "   ← 엔터")
    print(f"  2) 기존 서버를 브라우저로 열기 (예전 코드일 수 있음)")
    print("  3) 종료")
    줄("-")
    try:
        선택 = input("  번호 [1]: ").strip() or "1"
    except EOFError:
        선택 = "1"

    if 선택 == "2":
        try:
            webbrowser.open(f"http://localhost:{포트}")
        except Exception:  # noqa: BLE001
            pass
        print()
        print("  기존 서버를 열었습니다. 오류가 계속 나면 창을 모두 닫고 다시 실행하세요.")
        input("  엔터를 누르면 이 창이 닫힙니다...")
        return False
    if 선택 == "3":
        return False

    if 새포트 is None:
        print("  빈 포트를 찾지 못했습니다. 창을 모두 닫고 다시 시도하세요.")
        input("  엔터를 누르면 창이 닫힙니다...")
        return False
    포트 = 새포트
    print()
    print(f"  포트 {포트} 로 새로 실행합니다.")
    print("  ※ 예전 서버도 계속 켜져 있으니, 헷갈리지 않게 나중에 그 창은 닫아주세요.")
    print()
    return True


def 브라우저_열기(포트번호, 최대대기=60):
    """서버가 실제로 응답할 때까지 기다린 뒤 브라우저를 한 번만 엽니다."""
    시작 = time.time()
    while time.time() - 시작 < 최대대기:
        if 포트_열렸나(포트번호):
            time.sleep(1.0)          # 서버가 첫 페이지를 준비할 여유
            try:
                webbrowser.open(f"http://localhost:{포트번호}")
            except Exception:         # noqa: BLE001
                pass
            return
        time.sleep(0.4)
    print()
    print("[안내] 브라우저를 자동으로 열지 못했습니다.")
    print(f"       주소창에 http://localhost:{포트번호} 을 직접 입력하세요.")


def 줄(문자="=", 길이=62):
    print(문자 * 길이)


def 랜_주소_목록():
    """같은 와이파이에서 접속할 수 있는 사설 IP 주소들을 찾습니다."""
    주소 = set()

    # 외부로 나가는 경로의 로컬 IP (가장 정확한 방법)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        주소.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    # 보조: 호스트 이름으로 조회
    try:
        for 정보 in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            주소.add(정보[4][0])
    except OSError:
        pass

    사설 = [a for a in 주소
          if a.startswith(("192.168.", "10.")) or
          (a.startswith("172.") and 16 <= int(a.split(".")[1]) <= 31)]
    return sorted(사설)


def 패키지_설치_필요한가():
    빠진것 = []
    for 이름 in 필수_패키지:
        try:
            __import__(이름)
        except ImportError:
            빠진것.append(이름)
    return 빠진것


def 패키지_설치():
    print("필요한 패키지를 설치합니다. 처음 실행이면 몇 분 걸릴 수 있어요...")
    print()
    결과 = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r",
         os.path.join(앱_폴더, "requirements.txt")],
        cwd=앱_폴더,
    )
    print()
    if 결과.returncode != 0:
        줄()
        print("[오류] 패키지 설치에 실패했습니다.")
        print()
        print("아래를 확인해 보세요.")
        print("  1. 인터넷에 연결되어 있는지")
        print("  2. 회사 네트워크의 프록시/방화벽에 막히지 않았는지")
        print("  3. 아래 명령을 직접 실행했을 때 어떤 오류가 나오는지")
        print(f'     "{sys.executable}" -m pip install -r requirements.txt')
        줄()
        return False
    return True


def 비밀번호_확인():
    경로 = os.path.join(앱_폴더, ".streamlit", "secrets.toml")
    if os.path.exists(경로):
        return
    print("[주의] .streamlit\\secrets.toml 파일이 없습니다.")
    print("       .streamlit\\secrets.toml.example 을 같은 폴더에")
    print("       secrets.toml 이름으로 복사한 뒤 비밀번호를 바꿔주세요.")
    print("       지금은 기본 비밀번호 changeme123 으로 실행됩니다.")
    print()


def main():
    os.chdir(앱_폴더)

    줄()
    print("  개인 대시보드")
    print("  대출 / 환율 / 재산세 / 연봉")
    줄()
    print()
    print(f"파이썬: {sys.version.split()[0]}  ({sys.executable})")
    print(f"폴더  : {앱_폴더}")
    print()

    global 포트
    if 포트_열렸나(포트):
        if not 이미_실행중_처리():
            return 0

    빠진것 = 패키지_설치_필요한가()
    if 빠진것:
        print(f"설치가 필요한 패키지: {', '.join(빠진것)}")
        if not 패키지_설치():
            input("\n엔터를 누르면 창이 닫힙니다...")
            return 1
        print("설치 완료.")
        print()

    비밀번호_확인()

    줄("-")
    print("접속 주소")
    줄("-")
    print(f"  이 PC에서        :  http://localhost:{포트}")
    주소목록 = 랜_주소_목록()
    if 주소목록:
        for a in 주소목록:
            print(f"  같은 와이파이에서:  http://{a}:{포트}")
        print()
        print("  휴대폰 브라우저에 위 주소를 입력하세요.")
        print("  (접속이 안 되면 Windows 방화벽에서 Python 의 네트워크 접근을 허용해 주세요)")
    else:
        print("  같은 와이파이 주소를 찾지 못했습니다. 네트워크 연결을 확인하세요.")
    print()
    print("  다른 와이파이 / LTE 에서 접속하려면 '외부접속_설정_가이드.md' 를 보세요.")
    줄("-")
    print()
    브라우저_사용 = "--nobrowser" not in sys.argv
    if 브라우저_사용:
        print("서버를 시작합니다. 준비되면 브라우저가 자동으로 열립니다.")
    else:
        print("서버를 시작합니다. (--nobrowser 옵션으로 브라우저 자동 실행을 껐습니다)")
    print("종료하려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.")
    print()
    print("  ※ 아래에 'External URL' 이 표시되더라도 공유기 설정 없이는")
    print("    외부에서 접속되지 않습니다. 밖에서 쓰려면 가이드 문서를 보세요.")
    print()

    if 브라우저_사용:
        threading.Thread(target=브라우저_열기, args=(포트,), daemon=True).start()

    # headless=true : Streamlit 이 브라우저를 따로 열지 않도록(중복 탭 방지)
    #                 첫 실행 시 이메일 입력 요청도 건너뜁니다.
    명령 = [sys.executable, "-m", "streamlit", "run", "Home.py",
          "--server.port", str(포트),
          "--server.address", "0.0.0.0",
          "--server.headless", "true"]
    try:
        return subprocess.call(명령, cwd=앱_폴더)
    except KeyboardInterrupt:
        print("\n종료했습니다.")
        return 0


if __name__ == "__main__":
    코드 = main()
    if 코드:
        input("\n엔터를 누르면 창이 닫힙니다...")
    sys.exit(코드)
