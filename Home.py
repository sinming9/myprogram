"""
==========================================================================
개인 대시보드 - 시작 파일 (사이드바 묶음)
==========================================================================
이 파일은 **사이드바를 묶음별로 나누는 일만** 합니다. 첫 화면 내용은
pages/0_홈.py 에 있습니다.

[왜 이렇게 나눴나]
  pages/ 폴더만 두면 Streamlit 이 파일 이름 순서대로 한 줄로 늘어놓아서
  '📈 시장 / 💼 내 자산 / 🧮 계산기 / ⚙️ 도구' 같은 묶음 제목을 달 수
  없습니다. 묶으려면 시작 파일이 st.navigation 으로 목록을 직접 넘겨야
  하고, 그러면 시작 파일 자신은 화면을 그리지 않고 고른 페이지를 돌리는
  역할만 합니다.

[메뉴를 바꾸려면]
  ui.py 의 메뉴묶음 한 곳만 고치면 됩니다. 사이드바·페이지 위 알약 줄·
  첫 화면 목록이 모두 그 목록을 씁니다.

[Streamlit Cloud]
  시작 파일(Main file path)은 그대로 Home.py 입니다. 바꿀 것 없습니다.
==========================================================================
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui  # noqa: E402
from auth import _세션_유효한가  # noqa: E402

# 로그인하기 전에는 사이드바에 페이지 목록을 보이지 않습니다.
# (어느 페이지로 가든 로그인 화면이 먼저 나오지만, 목록조차 안 보이는 편이
#  깔끔합니다. 로그인하면 바로 다시 그려져 목록이 나타납니다.)
로그인됨 = _세션_유효한가()

# ★ ui.py 가 예전 것(네비게이션 함수가 없는 판)이면 앱 전체가 AttributeError
#   로 멈췄습니다(GitHub 에 Home.py 만 먼저 올라갔을 때 실제로 그랬습니다).
#   그럴 땐 pages/ 폴더 파일로 기본 메뉴를 만들어 띄우고 안내만 합니다.
if hasattr(ui, "네비게이션"):
    구성 = ui.네비게이션()
else:
    st.warning("**ui.py 가 예전 버전입니다.** GitHub 에 새 ui.py 를 올리면 "
               "메뉴가 묶음별로 정리됩니다. 지금은 기본 메뉴로 보여 드립니다.",
               icon="🔧")
    폴더 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
    구성 = [st.Page(os.path.join("pages", f)) for f in sorted(os.listdir(폴더))
          if f.endswith(".py")]

페이지 = st.navigation(구성, position="sidebar" if 로그인됨 else "hidden")
페이지.run()

# ★ 로그인은 페이지 안(require_login)에서 일어납니다. 이번 실행에서 막
#   로그인했다면(주소 열쇠·로그인 생략 등 버튼 없이 들어온 경우) 목록이
#   '숨김' 으로 그려진 채 남으므로 한 번 더 그려서 사이드바를 띄웁니다.
if not 로그인됨 and _세션_유효한가():
    st.rerun()
