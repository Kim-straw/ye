"""기본 데이터 넣기.

- 활동(교내 프로그램·대외활동): 가상 데이터 없음. 직접 확인한 실제 학교 RSS 글만 넣습니다.
- 학과명: 확인되지 않았습니다. 실제 학과명으로 고쳐야 합니다.
- 직무 요건(JOBS): 아직 샘플입니다(화면에 '샘플' 표시). 잡알리오 API 연결 후 실제 공고로 바꿀 예정.
- 실제 학생 개인정보는 넣지 않습니다.
실행: python -m app.seed   (spec-platform 폴더에서)
"""

from sqlalchemy import select

from . import rss_import
from .db import Base, Department, Job, JobRequirement, School, SessionLocal, Spec, Tag, engine, migrate_users

TAGS = ["개발", "데이터", "AI", "마케팅", "경영", "글쓰기", "디자인", "창업", "공공", "봉사", "어학", "상담", "리더십", "영상",
        # 아래는 세종캠퍼스 학과에 맞춰 추가한 분야 (앞의 순서는 바꾸지 말 것: 테스트와 화면이 번호에 기대고 있음)
        "반도체", "바이오·보건", "환경", "스포츠", "문화·예술", "통계", "보안"]

# (단과대, 학과/전공, 관련 태그)
# 출처: 입학처 학과 안내·모집요강, 위키백과, 나무위키(2025~2026 자료를 모은 것). 공식 현행 목록과 대조해 확인하지 못함.
# [확인 필요] 표시는 자료마다 이름이나 소속이 달라 불확실한 항목.
DEPARTMENTS = [
    ("과학기술대학", "응용수리과학부 데이터계산과학전공", ["데이터", "AI", "통계"]),
    ("과학기술대학", "반도체물리학부", ["반도체", "개발"]),  # [확인 필요] 자료에 따라 '디스플레이·반도체물리학부'
    ("과학기술대학", "신소재화학과", ["환경", "반도체"]),
    ("과학기술대학", "컴퓨터소프트웨어학과", ["개발", "데이터", "AI"]),
    ("과학기술대학", "전자및정보공학과", ["개발", "반도체"]),
    ("과학기술대학", "생명정보공학과", ["바이오·보건", "데이터"]),
    ("과학기술대학", "식품생명공학과", ["바이오·보건", "창업"]),
    ("과학기술대학", "전자·기계융합공학과", ["개발", "반도체"]),
    ("과학기술대학", "환경시스템공학과", ["환경", "공공"]),
    ("과학기술대학", "미래모빌리티학과", ["개발", "AI", "환경"]),
    ("과학기술대학", "지능형반도체공학과", ["반도체", "AI"]),
    ("과학기술대학", "인공지능사이버보안학과", ["AI", "보안", "개발"]),
    ("과학기술대학", "디지털헬스케어공학과", ["바이오·보건", "데이터", "AI"]),
    ("과학기술대학", "광역 자유전공학부(과학기술)", ["개발", "데이터"]),  # [확인 필요] 2026학년도 모집요강에 신설로 표기
    ("약학대학", "약학과", ["바이오·보건", "봉사"]),
    ("약학대학", "첨단융합신약학과", ["바이오·보건", "데이터"]),
    ("글로벌비즈니스대학", "글로벌학부 한국학전공", ["문화·예술", "글쓰기"]),
    ("글로벌비즈니스대학", "글로벌학부 중국학전공", ["어학", "경영"]),
    ("글로벌비즈니스대학", "글로벌학부 영미학전공", ["어학", "글쓰기"]),
    ("글로벌비즈니스대학", "글로벌학부 독일학전공", ["어학", "문화·예술"]),
    ("글로벌비즈니스대학", "융합경영학부 글로벌경영전공", ["경영", "마케팅", "창업"]),
    ("글로벌비즈니스대학", "융합경영학부 디지털경영전공", ["경영", "데이터", "마케팅"]),
    ("공공정책대학", "정부행정학부", ["공공", "글쓰기", "리더십"]),
    ("공공정책대학", "공공사회·통일외교학부 공공사회학전공", ["공공", "봉사", "상담"]),
    ("공공정책대학", "공공사회·통일외교학부 통일외교안보전공", ["공공", "어학", "글쓰기"]),
    ("공공정책대학", "경제통계학부 경제정책학전공", ["공공", "통계", "경영"]),
    ("공공정책대학", "경제통계학부 국가통계전공", ["통계", "데이터", "공공"]),
    ("공공정책대학", "경제통계학부 빅데이터전공", ["데이터", "통계", "AI"]),
    ("공공정책대학", "빅데이터사이언스학부", ["데이터", "AI", "통계"]),
    ("문화스포츠대학", "국제스포츠학부 스포츠과학전공", ["스포츠", "바이오·보건"]),
    ("문화스포츠대학", "국제스포츠학부 스포츠비즈니스전공", ["스포츠", "경영", "마케팅"]),
    ("문화스포츠대학", "문화유산융합학부 고고미술사학전공", ["문화·예술", "글쓰기"]),
    ("문화스포츠대학", "문화유산융합학부 문화ICT융합전공", ["문화·예술", "개발", "디자인"]),
    ("문화스포츠대학", "문화창의학부 미디어문예창작전공", ["글쓰기", "영상", "디자인"]),  # [확인 필요] 문화창의학부 하위 전공명이 자료마다 다름
    ("문화스포츠대학", "문화창의학부 문화콘텐츠전공", ["문화·예술", "영상", "마케팅"]),  # [확인 필요]
    ("스마트도시학부", "스마트도시학부", ["공공", "데이터", "환경"]),  # [확인 필요] 소속 전공·운영 여부 확인 못 함
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


def _fill(db) -> int:
    """기본 데이터(학교, 분야, 스펙, 학과, 직무)와 확인된 실제 공지 스냅샷을 채움. 저장한 공지 개수를 돌려줌."""
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
    return added


def run():
    """DB를 통째로 지우고 다시 만듦 (내 PC에서 처음부터 다시 할 때. 서버에서는 쓰지 말 것)"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    added = _fill(db)
    db.close()
    print(f"기본 데이터 입력 완료 (실제 학교 공지 {added}개)")


def ensure() -> bool:
    """서버가 켜질 때 부르는 안전한 버전: 테이블이 없으면 만들고, DB가 비어 있을 때만 기본 데이터를 채움.
    이미 데이터가 있으면 아무것도 지우지 않음. 새로 채웠으면 True."""
    Base.metadata.create_all(engine)
    try:
        added = migrate_users(engine)
        if added:
            print(f"[DB 정리] users 테이블에 칸 추가: {', '.join(added)}")
    except Exception as e:  # 실패해도 서버는 켜지게. DB 주소·비밀번호가 담길 수 있는 오류 문구 대신 종류만 남김
        print(f"[DB 정리 실패] {type(e).__name__}")
    db = SessionLocal()
    try:
        if db.scalars(select(School)).first() is None:
            _fill(db)
            return True
        return False
    finally:
        db.close()


if __name__ == "__main__":
    run()
