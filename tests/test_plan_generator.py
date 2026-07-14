import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.generation.plan_generator import (
    BookPlan,
    ChapterWithCount,
    LessonStub,
    generate_plan,
    split_candidate_chapters,
)
from app.models import Base, Book, Chapter, Chunk, Lesson, Plan


class _StubStructuredModel:
    """Stands in for `ChatOpenAI(...).with_structured_output(BookPlan)` in tests."""

    def __init__(self, book_plan: BookPlan):
        self.book_plan = book_plan
        self.calls: list[object] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.book_plan


class _AssertGeneratingStatusModel:
    """Confirms the Plan row is already visible with status='generating' at the
    moment the (slow) LLM call would happen - proves the ordering without needing
    real concurrency."""

    def __init__(self, book_plan: BookPlan, session, book_id: int):
        self.book_plan = book_plan
        self.session = session
        self.book_id = book_id

    def invoke(self, messages):
        plan = self.session.query(Plan).filter_by(book_id=self.book_id).one()
        assert plan.status == "generating"
        return self.book_plan


class _RaisingModel:
    def invoke(self, messages):
        raise RuntimeError("simulated model failure")


def _make_chapter(order_index: int, title: str) -> Chapter:
    return Chapter(order_index=order_index, title=title, start_page=0, end_page=0, summary="a summary")


def test_split_candidate_chapters_by_threshold():
    ch_a = ChapterWithCount(_make_chapter(0, "Cover"), 0)
    ch_b = ChapterWithCount(_make_chapter(1, "Copyright"), 1)
    ch_c = ChapterWithCount(_make_chapter(2, "Chapter 1"), 20)
    ch_d = ChapterWithCount(_make_chapter(3, "Chapter 2"), 45)

    candidates, context_only = split_candidate_chapters([ch_a, ch_b, ch_c, ch_d], min_chunks=8)

    assert [c.chapter.title for c in candidates] == ["Chapter 1", "Chapter 2"]
    assert [c.chapter.title for c in context_only] == ["Cover", "Copyright"]


def _make_test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_book(session, num_content_chapters=2):
    book = Book(title="Test Book", source_filename="test.pdf", num_pages=100, status="parsed")
    session.add(book)
    session.flush()

    chapters = [
        Chapter(book_id=book.id, order_index=0, title="Cover", start_page=0, end_page=0, summary=None),
    ]
    for i in range(num_content_chapters):
        chapters.append(
            Chapter(
                book_id=book.id,
                order_index=i + 1,
                title=f"Chapter {i + 1}",
                start_page=i * 10,
                end_page=i * 10 + 9,
                summary=f"Summary of chapter {i + 1}",
            )
        )
    session.add_all(chapters)
    session.flush()

    # Cover: 0 chunks; each real chapter: 10 chunks (above threshold of 8)
    for i, chapter in enumerate(chapters[1:]):
        for j in range(10):
            session.add(Chunk(chapter_id=chapter.id, order_index=j, token_count=50, text=f"text {j}"))
    session.commit()

    return book, chapters


def test_generate_plan_persists_lessons():
    session = _make_test_session()
    book, chapters = _seed_book(session, num_content_chapters=2)
    real_chapter_ids = [c.id for c in chapters[1:]]

    stub_plan = BookPlan(
        lessons=[
            LessonStub(title="Lesson A", topic_summary="Covers the first idea.", source_chapter_ids=[real_chapter_ids[0]]),
            LessonStub(title="Lesson B", topic_summary="Covers the second idea.", source_chapter_ids=[real_chapter_ids[1]]),
        ]
    )
    stub_model = _StubStructuredModel(stub_plan)

    plan = generate_plan(book.id, model=stub_model, session=session)

    assert plan.id is not None
    lessons = session.query(Lesson).filter_by(plan_id=plan.id).order_by(Lesson.order_index).all()
    assert [l.title for l in lessons] == ["Lesson A", "Lesson B"]
    assert [l.order_index for l in lessons] == [0, 1]
    assert json.loads(lessons[0].source_chapter_ids) == [real_chapter_ids[0]]
    assert len(stub_model.calls) == 1


def test_generate_plan_refuses_without_force_when_plan_exists():
    session = _make_test_session()
    book, chapters = _seed_book(session, num_content_chapters=1)
    real_chapter_id = chapters[1].id

    stub_plan = BookPlan(
        lessons=[LessonStub(title="Lesson A", topic_summary="x", source_chapter_ids=[real_chapter_id])]
    )
    generate_plan(book.id, model=_StubStructuredModel(stub_plan), session=session)

    with pytest.raises(ValueError):
        generate_plan(book.id, model=_StubStructuredModel(stub_plan), session=session)


def test_generate_plan_force_replaces_existing_plan():
    session = _make_test_session()
    book, chapters = _seed_book(session, num_content_chapters=1)
    real_chapter_id = chapters[1].id

    first_plan_stub = BookPlan(
        lessons=[LessonStub(title="Old Lesson", topic_summary="x", source_chapter_ids=[real_chapter_id])]
    )
    generate_plan(book.id, model=_StubStructuredModel(first_plan_stub), session=session)

    second_plan_stub = BookPlan(
        lessons=[LessonStub(title="New Lesson", topic_summary="y", source_chapter_ids=[real_chapter_id])]
    )
    second_plan = generate_plan(book.id, force=True, model=_StubStructuredModel(second_plan_stub), session=session)

    all_plans_for_book = session.query(Plan).filter_by(book_id=book.id).all()
    assert [p.id for p in all_plans_for_book] == [second_plan.id]

    all_lesson_titles = [l.title for l in session.query(Lesson).filter_by(book_id=book.id).all()]
    assert all_lesson_titles == ["New Lesson"]


def test_generate_plan_shows_generating_status_before_completing():
    session = _make_test_session()
    book, chapters = _seed_book(session, num_content_chapters=1)
    real_chapter_id = chapters[1].id

    stub_plan = BookPlan(
        lessons=[LessonStub(title="Lesson A", topic_summary="x", source_chapter_ids=[real_chapter_id])]
    )
    model = _AssertGeneratingStatusModel(stub_plan, session, book.id)

    plan = generate_plan(book.id, model=model, session=session)

    assert plan.status == "complete"


def test_generate_plan_marks_failed_on_exception():
    session = _make_test_session()
    book, chapters = _seed_book(session, num_content_chapters=1)

    with pytest.raises(RuntimeError):
        generate_plan(book.id, model=_RaisingModel(), session=session)

    plan = session.query(Plan).filter_by(book_id=book.id).one()
    assert plan.status == "failed"
