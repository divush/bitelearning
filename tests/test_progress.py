import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Book, Lesson, Plan
from app.progress import get_progress_summary, mark_lesson_complete, mark_lesson_incomplete


def _make_test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session, num_lessons=3):
    book = Book(title="Test Book", source_filename="test.pdf", num_pages=10, status="parsed")
    session.add(book)
    session.flush()

    plan = Plan(book_id=book.id, status="complete")
    session.add(plan)
    session.flush()

    lessons = []
    for i in range(num_lessons):
        lesson = Lesson(
            plan_id=plan.id,
            book_id=book.id,
            order_index=i,
            title=f"Lesson {i + 1}",
            topic_summary="x",
            status="generated",
        )
        session.add(lesson)
        lessons.append(lesson)
    session.commit()
    return book, lessons


def test_mark_lesson_complete_sets_fields():
    session = _make_test_session()
    book, lessons = _seed(session)

    lesson = mark_lesson_complete(book.id, 0, session=session)

    assert lesson.is_complete is True
    assert isinstance(lesson.completed_at, datetime.datetime)


def test_mark_lesson_incomplete_resets_fields():
    session = _make_test_session()
    book, lessons = _seed(session)
    mark_lesson_complete(book.id, 0, session=session)

    lesson = mark_lesson_incomplete(book.id, 0, session=session)

    assert lesson.is_complete is False
    assert lesson.completed_at is None


def test_mark_lesson_complete_rejects_out_of_range_index():
    session = _make_test_session()
    book, lessons = _seed(session)

    with pytest.raises(ValueError):
        mark_lesson_complete(book.id, 99, session=session)


def test_mark_lesson_complete_rejects_non_generated_lesson():
    session = _make_test_session()
    book, lessons = _seed(session, num_lessons=1)
    lessons[0].status = "planned"
    session.commit()

    with pytest.raises(ValueError):
        mark_lesson_complete(book.id, 0, session=session)


def test_get_progress_summary_computes_counts_and_last_completed():
    session = _make_test_session()
    book, lessons = _seed(session, num_lessons=3)

    mark_lesson_complete(book.id, 0, session=session)
    mark_lesson_complete(book.id, 2, session=session)

    summary = get_progress_summary(book.id, session=session)

    assert summary.total_lessons == 3
    assert summary.completed_count == 2
    assert summary.last_completed_at is not None
    assert [lp.is_complete for lp in summary.lessons] == [True, False, True]
