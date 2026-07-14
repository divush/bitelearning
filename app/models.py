import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


class LearnerProfile(Base):
    """Singleton row (id=1): standing, cross-book record of how the user likes to learn."""

    __tablename__ = "learner_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    example_first_vs_theory_first: Mapped[str | None] = mapped_column(String, nullable=True)
    session_length_pref: Mapped[str | None] = mapped_column(String, nullable=True)
    depth_vs_breadth: Mapped[str | None] = mapped_column(String, nullable=True)
    tone_pref: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_filename: Mapped[str] = mapped_column(String, nullable=False)
    num_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="uploaded")  # uploaded/parsing/parsed/failed
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="book", cascade="all, delete-orphan")
    context: Mapped["BookContext"] = relationship(back_populates="book", uselist=False, cascade="all, delete-orphan")
    plans: Mapped[list["Plan"]] = relationship(back_populates="book", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # populated in Plan Generation milestone

    book: Mapped["Book"] = relationship(back_populates="chapters")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    chapter: Mapped["Chapter"] = relationship(back_populates="chunks")


class BookContext(Base):
    __tablename__ = "book_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), unique=True, nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    prior_familiarity: Mapped[str | None] = mapped_column(Text, nullable=True)
    focus_areas: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_areas: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    book: Mapped["Book"] = relationship(back_populates="context")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="generating")  # generating/complete/failed
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    book: Mapped["Book"] = relationship(back_populates="plans")
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Lesson(Base):
    """One item in a Plan. Also carries the per-book, per-lesson completion state
    (folded in rather than a separate ProgressRecord table, since it's strictly 1:1)."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    topic_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_references: Mapped[str | None] = mapped_column(Text, nullable=True)
    exercises: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chapter_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[int]

    status: Mapped[str] = mapped_column(String, default="planned")  # planned/generating/generated/failed

    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow)

    plan: Mapped["Plan"] = relationship(back_populates="lessons")
