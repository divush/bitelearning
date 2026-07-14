"""Progress tracking: per-book, per-lesson completion state. Deliberately minimal -
a completion flag + timestamp, no grading or comprehension signal (see requirements
doc non-goals). Lessons are addressed by (book_id, order_index), consistent with
how scripts/generate_lessons.py's --lesson-index already addresses them.
"""

import datetime
from typing import NamedTuple

from app.db import get_session
from app.models import Lesson


class LessonProgress(NamedTuple):
    order_index: int
    title: str
    is_complete: bool
    completed_at: datetime.datetime | None


class ProgressSummary(NamedTuple):
    total_lessons: int
    completed_count: int
    last_completed_at: datetime.datetime | None
    lessons: list[LessonProgress]


def _get_lesson(session, book_id: int, order_index: int) -> Lesson:
    lesson = session.query(Lesson).filter_by(book_id=book_id, order_index=order_index).one_or_none()
    if lesson is None:
        raise ValueError(f"No lesson at order_index={order_index} for book {book_id}")
    return lesson


def mark_lesson_complete(book_id: int, order_index: int, session=None) -> Lesson:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        lesson = _get_lesson(session, book_id, order_index)
        if lesson.status != "generated":
            raise ValueError(
                f"Lesson {order_index} ({lesson.title!r}) has status={lesson.status!r}, "
                "not 'generated' - can't mark unwritten content complete."
            )
        lesson.is_complete = True
        lesson.completed_at = datetime.datetime.utcnow()
        session.add(lesson)
        session.commit()
        return lesson
    finally:
        if owns_session:
            session.close()


def mark_lesson_incomplete(book_id: int, order_index: int, session=None) -> Lesson:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        lesson = _get_lesson(session, book_id, order_index)
        lesson.is_complete = False
        lesson.completed_at = None
        session.add(lesson)
        session.commit()
        return lesson
    finally:
        if owns_session:
            session.close()


def get_progress_summary(book_id: int, session=None) -> ProgressSummary:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        lessons = session.query(Lesson).filter_by(book_id=book_id).order_by(Lesson.order_index).all()
        lesson_progress = [
            LessonProgress(l.order_index, l.title, l.is_complete, l.completed_at) for l in lessons
        ]
        completed = [lp for lp in lesson_progress if lp.is_complete]
        last_completed_at = max((lp.completed_at for lp in completed), default=None)
        return ProgressSummary(
            total_lessons=len(lesson_progress),
            completed_count=len(completed),
            last_completed_at=last_completed_at,
            lessons=lesson_progress,
        )
    finally:
        if owns_session:
            session.close()
