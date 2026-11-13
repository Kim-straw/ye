"""기본 데이터 넣기.

- 활동(교내 프로그램·대외활동): 가상 데이터 없음. 직접 확인한 실제 학교 RSS 글만 넣습니다.
- 학과명: 확인되지 않았습니다. 실제 학과명으로 고쳐야 합니다.
- 직무 요건(JOBS): 아직 샘플입니다(화면에 '샘플' 표시). 잡알리오 API 연결 후 실제 공고로 바꿀 예정.
- 실제 학생 개인정보는 넣지 않습니다.
실행: python -m app.seed   (spec-platform 폴더에서)
"""

from . import rss_import
from .db import Base, Department, Job, JobRequirement, School, SessionLocal, Spec, Tag, engine

TAGS = ["개발", "데이터", "AI", "마케팅", "경영", "글쓰기", "디자인", "창업", "공공", "봉사", "어학", "상담", "리더십", "영상"]

# (단과대, 학과, 관련 태그)  ※ 학과명은 확인 필요
DEPARTMENTS = [
    ("과학기술대학", "컴퓨터융합소프트웨어학과", ["개발", "데이터", "AI"]),
    ("과학기술대학", "전자및정보공학과", ["개발", "AI"]),
    ("과학기술대학", "데이터계산과학전공", ["데이터", "AI"]),
    ("글로벌비즈니스대학", "글로벌경영전공", ["경영", "마케팅", "창업"]),
    ("글로벌비즈니스대학", "디지털경영전공", ["경영", "데이터", "마케팅"]),
    ("공공정책대학", "행정학전공", ["공공", "글쓰기"]),
    ("공공정책대학", "경제정책학전공", ["공공", "데이터"]),
    ("문화스포츠대학", "미디어문예창작전공", ["글쓰기", "영상", "디자인"]),
]

# (이름, 종류, 점수형 여부)
SPECS = [
    ("정보처리기사", "자격증", False), ("SQLD", "자격증", False), ("ADsP", "자격증", False),
    ("컴퓨터활용능력 1급", "자격증", False), ("한국사능력검정 1급", "자격증", False),
    ("TOEIC", "어학", True), ("OPIc IM2 이상", "어학", False),
    ("개발 프로젝트 경험", "경험", False), ("인턴 경험", "경험", False), ("공모전 수상", "경험", False),
    ("서포터즈·기자단 경험", "경험", False), ("봉사활동 경험", "경험", False), ("창업 경험", "경험", False),
]

# (직무, 분야, 설명, [(스펙, 필수/우대, 최소값)])
JOBS = [
    ("백엔드 개발자", "사기업", "서버·API·DB를 설계하고 개발합니다.",
     [("개발 프로젝트 경험", "필수", None), ("정보처리기사", "우대", None), ("SQLD", "우대", None), ("인턴 경험", "우대", None)]),
    ("데이터 분석가", "사기업", "데이터를 수집·분석해 의사결정을 돕습니다.",
     [("ADsP", "필수", None), ("SQLD", "필수", None), ("개발 프로젝트 경험", "우대", None), ("공모전 수상", "우대", None)]),
    ("마케터", "사기업", "브랜드와 서비스의 홍보 전략을 기획합니다.",
     [("서포터즈·기자단 경험", "필수", None), ("TOEIC", "우대", 750), ("공모전 수상", "우대", None)]),
    ("공기업 전산직", "공기업", "기관의 정보시스템을 운영·개발합니다.",
     [("정보처리기사", "필수", None), ("TOEIC", "필수", 700), ("한국사능력검정 1급", "우대", None), ("컴퓨터활용능력 1급", "우대", None)]),
    ("공단 행정직", "공단", "기관의 행정·사업 운영을 담당합니다.",
     [("TOEIC", "필수", 700), ("한국사능력검정 1급", "우대", None), ("컴퓨터활용능력 1급", "우대", None), ("봉사활동 경험", "우대", None)]),
]

# 2026-11-13 로그인 없이 열리는 것을 확인한 실제 RSS(nipa.korea.ac.kr/bbs/fieldwork/575)의 글 3개.
# 인터넷 없이도 실제 데이터로 시작하기 위한 스냅샷. 최신 글은 python -m app.rss_import 로 가져옴.
VERIFIED_RSS_SNAPSHOT = """<rss version="2.0"><channel><title>RSS 게시판 2.0</title>
<item><title><![CDATA[ 제4회 현장실습학기제 우수 수기 공모전 수상작 및 인터뷰 ]]></title>
<link>/bbs/fieldwork/575/267131/artclView.do?layout=unknown</link><pubDate>2026-02-27 17:13:47.0</pubDate>
<description><![CDATA[ 세종현장실습지원센터 제4회 현장실습학기제 우수 수기 공모전 수상작 안내 ]]></description></item>
<item><title><![CDATA[ 제4회 현장실습학기제 우수사례 수기·영상 공모전 개최 ]]></title>
<link>/bbs/fieldwork/575/263629/artclView.do?layout=unknown</link><pubDate>2025-10-22 09:19:29.0</pubDate>
<description><![CDATA[ 세종현장실습온라인시스템 주소: http://coop.korea.ac.kr 세종현장실습온라인시스템 바로가기 ]]></description></item>
<item><title><![CDATA[ 제3회 현장실습학기제 우수 수기 공모전 수상작 ]]></title>
<link>/bbs/fieldwork/575/262791/artclView.do?layout=unknown</link><pubDate>2025-09-19 13:27:16.0</pubDate>
<description><![CDATA[ ]]></description></item>
</channel></rss>"""


def run():
    Base.metadata.drop_all(engine)  # 매번 새로 만듦 (사용자 데이터가 생기면 쓰면 안 됨)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    school = School(name="고려대학교", campus="세종캠퍼스")
    db.add(school)
    tags = {name: Tag(name=name) for name in TAGS}
    specs = {n: Spec(name=n, kind=k, has_score=s) for n, k, s in SPECS}
    db.add_all(list(tags.values()) + list(specs.values()))

    for college, name, tnames in DEPARTMENTS:
        db.add(Department(school=school, college=college, name=name, tags=[tags[t] for t in tnames]))

    db.flush()  # 창고에 임시로 넣어 school.id 번호를 먼저 발급받기
    for name, sector, desc, reqs in JOBS:
        db.add(Job(name=name, sector=sector, description=desc, requirements=[
            JobRequirement(spec=specs[s], level=lv, min_value=mv, source_url="") for s, lv, mv in reqs
        ]))

    # 실제 학교 공지 스냅샷을 교내 프로그램으로 저장 (rss_import와 같은 규칙: 수상작 글 제외 등)
    db.commit()
    feed = rss_import.NIPA_575
    added = rss_import.save_items(db, rss_import.parse_rss(VERIFIED_RSS_SNAPSHOT, feed["base"]), feed)

    db.commit()
    db.close()
    print(f"기본 데이터 입력 완료 (실제 학교 공지 {added}개)")


if __name__ == "__main__":
    run()
