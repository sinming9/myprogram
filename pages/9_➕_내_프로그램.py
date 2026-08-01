import os
import sys
import traceback

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import addons  # noqa: E402
import storage  # noqa: E402
import ui  # noqa: E402
from auth import require_login, 로그아웃_버튼  # noqa: E402

require_login(page_title="내 프로그램", page_icon="➕", layout="centered")
ui.모바일_스타일()
로그아웃_버튼()
ui.테마_안내()
storage.저장소_사이드바()

st.title("➕ 내 프로그램")
st.caption("`myapps/` 폴더에 넣은 .py 파일들이 여기에 자동으로 나타납니다.")

새로고침 = st.sidebar.button("🔄 내 프로그램 다시 읽기", width="stretch",
                        help="파일을 수정한 뒤 누르면 바로 반영됩니다")

목록 = addons.전체_불러오기(새로고침=새로고침)

if not 목록:
    st.info("`myapps/` 폴더에 아직 파일이 없습니다.", icon="📂")
    with st.expander("📝 새 프로그램 만드는 방법", expanded=True):
        st.markdown(
            "`myapps/` 폴더에 아무 이름으로 `.py` 파일을 만들고 아래 내용을 넣어보세요.\n"
            "저장한 뒤 왼쪽 **🔄 내 프로그램 다시 읽기** 를 누르면 바로 나타납니다."
        )
        st.code(
            '제목 = "내 계산기"\n'
            '아이콘 = "🧮"\n'
            '설명 = "간단한 계산을 해봅니다"\n'
            '\n'
            '\n'
            'def 실행():\n'
            '    import streamlit as st\n'
            '\n'
            '    값 = st.number_input("숫자를 넣어보세요", value=10)\n'
            '    st.metric("두 배", f"{값 * 2:,.0f}")\n',
            language="python",
        )
    st.stop()

# ---- 오류가 있는 파일들 먼저 알려주기 ----
문제 = [(이름, 오류) for 정보, 오류, 이름 in 목록 if 오류]
if 문제:
    st.warning(f"{len(문제)}개 파일에 문제가 있습니다.", icon="⚠️")
    for 이름, 오류 in 문제:
        with st.expander(f"⚠️ {이름}.py — 자세히 보기"):
            st.code(오류, language="text")

정상 = [정보 for 정보, 오류, _ in 목록 if 정보 and 오류 is None]
if not 정상:
    st.error("실행할 수 있는 프로그램이 없습니다. 위 오류 내용을 확인해 주세요.")
    st.stop()

# ---- 프로그램 고르기 ----
if len(정상) == 1:
    고른것 = 정상[0]
else:
    이름표 = {f"{p['아이콘']} {p['제목']}": p for p in 정상}
    고른라벨 = st.selectbox("실행할 프로그램", list(이름표),
                        key="_애드온_선택")
    고른것 = 이름표[고른라벨]

st.divider()
st.markdown(f"## {고른것['아이콘']} {고른것['제목']}")
if 고른것["설명"]:
    st.caption(고른것["설명"])

# ---- 실행 (오류가 나도 페이지 전체가 죽지 않게 감싸기) ----
try:
    고른것["실행"]()
except Exception:  # noqa: BLE001
    st.error(f"'{고른것['이름']}.py' 실행 중 오류가 발생했습니다.", icon="🐞")
    with st.expander("오류 내용 보기", expanded=True):
        st.code(traceback.format_exc(), language="text")
    st.caption("파일을 수정한 뒤 왼쪽 **🔄 내 프로그램 다시 읽기** 를 누르세요.")

st.divider()
with st.expander("📂 파일 위치 / 만드는 방법"):
    st.markdown(f"폴더: `{addons.애드온_폴더}`")
    st.markdown(
        "- 파일 이름은 자유롭게 (번호·이모지 필요 없음). `_` 나 `.` 으로 시작하면 무시됩니다.\n"
        "- `제목` / `아이콘` / `설명` 변수는 없어도 되고, `실행()` 함수만 있으면 됩니다.\n"
        "- `app_kit` 의 도구를 쓸 수 있습니다: "
        "`from app_kit import 원, 만원, 억, 카드_줄, 날짜로, 숫자로, 표만들기, 저장, 불러오기`\n"
        "- 자료를 저장하려면 `저장(\"내키\", 값)` / `불러오기(\"내키\", 기본값)` 을 쓰세요.\n"
        "- 화면을 완전히 따로 만들고 싶으면 `pages/` 폴더에 파일을 넣으면 "
        "왼쪽 메뉴에 별도 항목으로 나타납니다. (템플릿: `pages/_템플릿.py.txt`)"
    )
