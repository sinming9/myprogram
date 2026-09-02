"""
==========================================================================
GitHub 업로드용 사본 만들기
==========================================================================
GitHub 웹페이지에 파일을 끌어다 놓는 방식은 `.gitignore` 를 **무시하고**
끌어놓은 것을 전부 올립니다. 그래서 비밀번호 파일(secrets.toml)과 개인
자료(data/)가 그대로 공개될 수 있습니다.

이 파일을 실행하면 그 두 가지를 뺀 안전한 사본을 옆 폴더에 만듭니다.
그 폴더의 내용물만 GitHub 에 올리면 됩니다.

[쓰는 법]
    업로드_준비_윈도우.bat  더블클릭
  또는
    py -3 업로드_준비.py

  ※ 이 PC 에서 `python` 이 Microsoft Store 안내창만 띄우면 `py -3` 을 쓰세요.

[안전장치]
  사본을 만든 뒤 다시 훑어서, 빠뜨린 비밀 파일이 하나라도 있으면
  경고를 띄우고 사본을 지웁니다. 반쯤 안전한 폴더를 남기지 않습니다.
==========================================================================
"""

import os
import shutil
import sys

앱_폴더 = os.path.dirname(os.path.abspath(__file__))
사본_이름 = "_업로드용"
사본_폴더 = os.path.join(os.path.dirname(앱_폴더), 사본_이름)


# --------------------------------------------------------------------------
# 무엇을 뺄지
# --------------------------------------------------------------------------
#  '비밀' 은 유출되면 곤란한 것, '군더더기' 는 없어도 앱이 도는 것입니다.
#  둘을 나눠 둔 이유는, 마지막 검사에서 '비밀' 만 실패로 처리하기 때문입니다.

비밀_폴더 = {"data"}                      # 연봉·재산세·순자산 …
비밀_파일 = {"secrets.toml"}              # 로그인 비밀번호 · GitHub 토큰

군더더기_폴더 = {
    ".git", "__pycache__", ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".claude", ".vscode", ".idea", 사본_이름,
}
군더더기_확장 = {".pyc", ".pyo", ".pyd", ".log", ".swp"}
군더더기_파일 = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _백업파일인가(이름: str) -> bool:
    """앱이 내려준 백업·설정 파일. 개인 금액이 들어 있어 뺍니다."""
    if not 이름.lower().endswith(".json"):
        return False
    조각 = ("_백업_", "_설정_", "순자산_", "연봉자료_", "재산세_",
          "대출계산기_", "자산배분_", "양도세_")
    return any(c in 이름 for c in 조각)


빠진것 = []


def 무엇을_뺄까(폴더, 이름들):
    """shutil.copytree 에 넘기는 함수. 뺄 이름의 집합을 돌려줍니다."""
    뺀다 = set()
    for 이름 in 이름들:
        전체 = os.path.join(폴더, 이름)
        상대 = os.path.relpath(전체, 앱_폴더).replace("\\", "/")

        if os.path.isdir(전체):
            if 이름 in 비밀_폴더:
                뺀다.add(이름)
                빠진것.append(("비밀", 상대 + "/", "개인 자료"))
            elif 이름 in 군더더기_폴더:
                뺀다.add(이름)
                빠진것.append(("군더더기", 상대 + "/", "올릴 필요 없음"))
            continue

        if 이름 in 비밀_파일:
            뺀다.add(이름)
            빠진것.append(("비밀", 상대, "비밀번호·토큰"))
        elif _백업파일인가(이름):
            뺀다.add(이름)
            빠진것.append(("비밀", 상대, "백업 파일 (금액 포함)"))
        elif 이름 in 군더더기_파일 or os.path.splitext(이름)[1] in 군더더기_확장:
            뺀다.add(이름)
            빠진것.append(("군더더기", 상대, "올릴 필요 없음"))
    return 뺀다


# --------------------------------------------------------------------------
# 사본 만들기
# --------------------------------------------------------------------------
def 사본_만들기():
    if os.path.exists(사본_폴더):
        print(f"이미 있는 사본을 지웁니다 — {사본_폴더}")
        shutil.rmtree(사본_폴더)
    shutil.copytree(앱_폴더, 사본_폴더, ignore=무엇을_뺄까)


def 마지막_검사():
    """사본 안에 비밀이 남아 있지 않은지 다시 훑습니다.

    빠뜨린 게 있으면 사본을 지웁니다. 반쯤 안전한 폴더를 남기면
    사용자가 그걸 올려 버릴 수 있습니다.
    """
    문제 = []
    for 뿌리, 폴더들, 파일들 in os.walk(사본_폴더):
        for 이름 in 폴더들:
            if 이름 in 비밀_폴더:
                문제.append(os.path.relpath(os.path.join(뿌리, 이름), 사본_폴더))
        for 이름 in 파일들:
            if 이름 in 비밀_파일 or _백업파일인가(이름):
                문제.append(os.path.relpath(os.path.join(뿌리, 이름), 사본_폴더))
    return 문제


def 항목_세기():
    것들 = sorted(os.listdir(사본_폴더))
    파일 = [x for x in 것들 if os.path.isfile(os.path.join(사본_폴더, x))]
    폴더 = [x for x in 것들 if os.path.isdir(os.path.join(사본_폴더, x))]
    return 파일, 폴더


def main():
    print("=" * 66)
    print(" GitHub 업로드용 사본 만들기")
    print("=" * 66)
    print(f" 원본 : {앱_폴더}")
    print(f" 사본 : {사본_폴더}")
    print()

    try:
        사본_만들기()
    except OSError as e:
        print(f"[실패] 사본을 만들지 못했습니다 — {e}")
        return 1

    비밀들 = [x for x in 빠진것 if x[0] == "비밀"]
    나머지 = [x for x in 빠진것 if x[0] != "비밀"]

    if 비밀들:
        print(" 뺀 것 — 올리면 안 되는 것")
        for _종류, 경로, 이유 in 비밀들:
            print(f"   x {경로:<40} ({이유})")
    else:
        print(" 뺄 비밀 파일이 없었습니다.")
        print("   (아직 비밀번호를 정하지 않았거나 자료를 저장한 적이 없는 상태)")
    print()

    if 나머지:
        print(f" 뺀 것 — 군더더기 {len(나머지)}개 "
              f"({', '.join(x[1] for x in 나머지[:5])}"
              f"{' …' if len(나머지) > 5 else ''})")
        print()

    문제 = 마지막_검사()
    if 문제:
        shutil.rmtree(사본_폴더, ignore_errors=True)
        print("=" * 66)
        print(" [중단] 사본에 비밀 파일이 남아 있어서 사본을 지웠습니다.")
        for p in 문제:
            print(f"   ! {p}")
        print(" 이 메시지를 그대로 알려주세요. 규칙을 고쳐야 합니다.")
        print("=" * 66)
        return 1

    파일, 폴더 = 항목_세기()
    print("=" * 66)
    print(f" 완료 — 파일 {len(파일)}개 + 폴더 {len(폴더)}개 "
          f"= {len(파일) + len(폴더)}개 항목")
    print("=" * 66)
    print(" 다음 순서:")
    print(f"   1. 탐색기에서 이 폴더를 **엽니다** : {사본_폴더}")
    print("   2. 폴더 자체를 끌지 말고, 안의 내용물을 전체 선택(Ctrl+A)")
    print("   3. GitHub 저장소의 'uploading an existing file' 점선 영역에 끌어놓기")
    print("   4. 맨 아래 초록색 Commit changes 클릭")
    print()
    print(" 자세한 내용은 외부접속_설정_가이드.md [2단계] 를 보세요.")
    return 0


if __name__ == "__main__":
    코드 = main()
    # 더블클릭으로 열면 창이 바로 닫혀서 결과를 못 봅니다. 그래서 기다립니다.
    # 다른 프로그램이 불러 쓸 때는 입력이 없으니 조용히 넘어갑니다.
    if os.name == "nt":
        try:
            input("\n엔터를 누르면 창이 닫힙니다. ")
        except (EOFError, OSError):
            pass
    sys.exit(코드)
