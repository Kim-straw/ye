"""창고(DB) 연결과 테이블 정의.

클래스 하나 = 테이블(엑셀 시트) 하나, 클래스 속성 하나 = 칸(열) 하나입니다.
"""
import os
import re
from datetime import date
from pathlib import Path

from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Table, Text, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

# 환경변수 SPEC_DB가 있으면 그 파일을 씀 (테스트가 실제 DB를 지우지 않도록 따로 쓰기 위함)
DB_PATH = Path(os.environ.get("SPEC_DB") or Path(__file__).resolve().parent.parent / "app.db")


def clean_database_url(raw: str) -> str:
    """Neon에서 복사한 글자에 'psql' 명령, 따옴표, 줄바꿈이 같이 붙어도 postgresql://... 주소 부분만 꺼냄"""
    m = re.search(r"postgres(?:ql)?://[^\s'\"]+", raw or "")
    return m.group(0) if m else (raw or "").strip()


def make_engine():
    """DATABASE_URL이 있으면 그 Postgres(예: Neon)에, 없으면 내 PC의 SQLite 파일(app.db)에 연결.
    서버(Render)는 재시작하면 파일이 사라져서, 서버에 올릴 때는 DATABASE_URL로 따로 둔 DB를 씀."""
    raw = os.environ.get("DATABASE_URL") or ""
    url = clean_database_url(raw)
    if url:
        if not url.startswith(("postgres://", "postgresql://")):
            # 비밀번호가 로그에 남지 않도록 값은 출력하지 않고 모양만 안내함
            raise RuntimeError("DATABASE_URL이 postgresql:// 로 시작하지 않습니다. Neon의 'Connection string' 주소만 붙여 넣어 주세요.")
        for old in ("postgres://", "postgresql://"):  # 서비스마다 주소 앞부분이 달라서 하나로 맞춤
            if url.startswith(old):
                url = "postgresql+psycopg://" + url[len(old):]
                break
        return create_engine(url, pool_pre_ping=True, pool_recycle=300)  # DB가 잠들었다 깨어나도 끊긴 연결을 다시 맺음
    return create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


# ---- 다대다 연결표: 값 없이 "누가 누구와 연결됐는지"만 적는 표 ----
department_tags = Table(
    "department_tags", Base.metadata,
    Column("department_id", ForeignKey("departments.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)
user_tags = Table(
    "user_tags", Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)
opportunity_tags = Table(
    "opportunity_tags", Base.metadata,
    Column("opportunity_id", ForeignKey("opportunities.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)
# "이 활동을 하면 이 스펙이 생긴다" (갭 분석 추천에 사용)
opportunity_specs = Table(
    "opportunity_specs", Base.metadata,
    Column("opportunity_id", ForeignKey("opportunities.id"), primary_key=True),
    Column("spec_id", ForeignKey("specs.id"), primary_key=True),
)


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    campus: Mapped[str] = mapped_column(String(30))
    departments: Mapped[list["Department"]] = relationship(back_populates="school")


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))  # 외래키: 어느 학교 소속인지
    college: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(50))
    school: Mapped[School] = relationship(back_populates="departments")
    tags: Mapped[list["Tag"]] = relationship(secondary=department_tags)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class Spec(Base):
    __tablename__ = "specs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # 자격증 / 어학 / 경험
    has_score: Mapped[bool] = mapped_column(Boolean, default=False)  # 토익처럼 점수가 있는 스펙


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    nickname: Mapped[str] = mapped_column(String(20))
    grade: Mapped[int] = mapped_column(Integer)           # 학년
    admission_year: Mapped[int] = mapped_column(Integer)  # 입학년도 (학번 전체는 받지 않음)
    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    mileage: Mapped[int] = mapped_column(Integer, default=0)  # 6단계용 자리만 마련
    department: Mapped[Department] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=user_tags)
    specs: Mapped[list["UserSpec"]] = relationship(cascade="all, delete-orphan")


class UserSpec(Base):
    """보유 스펙. 연결표지만 '점수' 값이 있어서 클래스로 만듦."""
    __tablename__ = "user_specs"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    spec_id: Mapped[int] = mapped_column(ForeignKey("specs.id"), primary_key=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    spec: Mapped[Spec] = relationship()


class Opportunity(Base):
    """교내 프로그램 + 대외활동을 한 테이블에. scope로 구분."""
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True)  # 외부 활동이면 비움
    scope: Mapped[str] = mapped_column(String(10))      # 교내 / 외부
    category: Mapped[str] = mapped_column(String(20))   # 비교과 / 서포터즈 / 기자단 / 공모전 ...
    title: Mapped[str] = mapped_column(String(100))
    host: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1~5, 학교 공지는 모름
    hours: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 총 소요시간(시간)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)      # RSS에는 마감일이 없음
    posted_at: Mapped[date | None] = mapped_column(Date, nullable=True)     # 공지 게시일
    url: Mapped[str] = mapped_column(String(300), default="")               # 원문 링크 (RSS 중복 판별에도 사용)
    source: Mapped[str] = mapped_column(String(10), default="rss")          # rss / manual (가상 데이터는 넣지 않음)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[Tag]] = relationship(secondary=opportunity_tags)
    specs: Mapped[list[Spec]] = relationship(secondary=opportunity_specs)
    reviews: Mapped[list["Review"]] = relationship(cascade="all, delete-orphan", order_by="Review.id.desc()")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1~5
    content: Mapped[str] = mapped_column(Text)
    user: Mapped[User | None] = relationship()


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    sector: Mapped[str] = mapped_column(String(10))  # 사기업 / 공기업 / 공단
    description: Mapped[str] = mapped_column(Text, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=True)
    # 아래 3개는 실제 채용공고(API)에서 온 직무에만 채워짐
    source_id: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 공고 번호 (중복 저장 방지)
    source_url: Mapped[str] = mapped_column(String(300), default="")           # 원문 공고 링크
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)         # 공고 마감일
    requirements: Mapped[list["JobRequirement"]] = relationship(cascade="all, delete-orphan")


class JobRequirement(Base):
    """채용공고의 자격요건. 합격자 스펙 대신 공고 기준을 씀(출처가 명확하므로)."""
    __tablename__ = "job_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    spec_id: Mapped[int] = mapped_column(ForeignKey("specs.id"))
    level: Mapped[str] = mapped_column(String(5))  # 필수 / 우대
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str] = mapped_column(String(300), default="")
    spec: Mapped[Spec] = relationship()


def get_db():
    """요청 하나마다 창고 출입증(세션)을 열고, 끝나면 반드시 닫음."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(engine)
