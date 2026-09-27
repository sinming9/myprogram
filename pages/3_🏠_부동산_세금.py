"""
==========================================================================
부동산 세금 — 재산세·종부세 + 양도소득세
==========================================================================
[두 페이지를 하나로 합친 이유]
  둘 다 '집' 을 기준으로 계산하고, 계산기 묶음에 비슷한 페이지가 셋이던
  것을 둘(대출 · 부동산 세금)로 줄였습니다.

[탭이 아니라 '고른 쪽만 돌리기' 인 이유]
  재산세 쪽은 표가 비면 st.stop() 으로 멈춥니다. st.tabs 로 둘을 한 번에
  그리면 그 순간 양도세 쪽도 같이 멈춥니다. 그래서 위에서 하나를 고르면
  그쪽 파일(views/)만 실행합니다. 서로의 입력 칸 key 가 부딪칠 일도
  없습니다.

[저장된 자료]
  예전과 같은 키(property_tax / capital_gains)를 그대로 씁니다. 전에
  넣어 둔 값이 그대로 나옵니다.

[바로 열기]  ?항목=양도세  를 붙이면 양도세 쪽으로 열립니다.
==========================================================================
"""

import os
import runpy
import sys

import streamlit as st

뿌리 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 뿌리)
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402

require_login(page_title="부동산 세금", page_icon="🏠", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

ui.페이지_메뉴(__file__)
st.title("🏠 부동산 세금")

항목들 = {
    "재산세": ("🏠 재산세 · 종부세", "재산세_종부세.py"),
    "양도세": ("🏷️ 양도소득세", "양도세.py"),
}

# 주소의 ?항목= 으로 처음 고를 쪽을 정할 수 있습니다 (다른 페이지의 링크용)
if "부동산세금_항목" not in st.session_state:
    처음 = st.query_params.get("항목", "재산세")
    st.session_state["부동산세금_항목"] = 처음 if 처음 in 항목들 else "재산세"

고른것 = st.segmented_control(
    "계산할 세금", list(항목들), format_func=lambda k: 항목들[k][0],
    key="부동산세금_항목", required=True, label_visibility="collapsed")
고른것 = 고른것 or "재산세"
st.query_params["항목"] = 고른것

runpy.run_path(os.path.join(뿌리, "views", 항목들[고른것][1]),
               run_name="__main__")
