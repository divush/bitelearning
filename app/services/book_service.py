"""The only layer allowed to import app.models/app.db/app.progress/app.generation/
app.ingestion. Converts ORM objects into the plain dataclasses in app.services.dto
before handing anything back to the web layer.
"""

import datetime
import json
import logging
from pathlib import Path

from app.config import BASE_DIR
from app.generation.lesson_generator import generate_book_lessons
from app.generation.plan_generator import generate_plan
from app.generation.summarizer import summarize_book
from app.ingestion.pipeline import ingest_book
from app.models import Book, BookContext, Chapter, Chunk, LearnerProfile, Lesson, Plan
from app.progress import mark_lesson_complete, mark_lesson_incomplete
from app.services.dto import (
    BookContextView,
    BookSummary,
    BookWorkspace,
    ExerciseView,
    LearnerProfileView,
    LessonDetail,
    PlanLessonRow,
    ReferenceView,
)

logger = logging.getLogger(__name__)

BOOKS_DIR = BASE_DIR / "data" / "books"


def get_books_dir() -> Path:
    return BOOKS_DIR


def list_books(session) -> list[BookSummary]:
    books = session.query(Book).order_by(Book.id).all()
    summaries = []
    for book in books:
        lessons = session.query(Lesson).filter_by(book_id=book.id).all()
        summaries.append(
            BookSummary(
                id=book.id,
                title=book.title,
                total_lessons=len(lessons),
                completed_count=sum(1 for l in lessons if l.is_complete),
            )
        )
    return summaries


def _format_elapsed(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs}s"


def get_book_workspace(session, book_id: int) -> BookWorkspace:
    book = session.query(Book).filter_by(id=book_id).one()
    plan = session.query(Plan).filter_by(book_id=book_id).one_or_none()
    lessons = session.query(Lesson).filter_by(book_id=book_id).order_by(Lesson.order_index).all()

    rows = [
        PlanLessonRow(
            order_index=l.order_index,
            title=l.title,
            is_complete=l.is_complete,
            is_generated=(l.status == "generated"),
            is_generating=(l.status == "generating"),
            is_failed=(l.status == "failed"),
        )
        for l in lessons
    ]

    chapters = session.query(Chapter).filter_by(book_id=book_id).all()
    summarizable_chapters = [
        c for c in chapters if session.query(Chunk).filter_by(chapter_id=c.id).count() > 0
    ]
    chapters_total = len(summarizable_chapters)
    chapters_summarized = sum(1 for c in summarizable_chapters if c.summary is not None)
    summarizing_chapters = bool(
        plan and plan.status == "generating" and chapters_summarized < chapters_total
    )

    plan_elapsed_display = None
    if plan and plan.status == "generating":
        elapsed_seconds = int((datetime.datetime.utcnow() - plan.created_at).total_seconds())
        plan_elapsed_display = _format_elapsed(max(elapsed_seconds, 0))

    generating_row = next((r for r in rows if r.is_generating), None)

    return BookWorkspace(
        book_id=book.id,
        title=book.title,
        num_pages=book.num_pages,
        total_lessons=len(rows),
        completed_count=sum(1 for r in rows if r.is_complete),
        lessons=rows,
        plan_status=plan.status if plan else None,
        plan_elapsed_display=plan_elapsed_display,
        lessons_generating=generating_row is not None,
        generated_count=sum(1 for r in rows if r.is_generated),
        current_lesson_title=generating_row.title if generating_row else None,
        chapters_total=chapters_total,
        chapters_summarized=chapters_summarized,
        summarizing_chapters=summarizing_chapters,
    )


def get_lesson_detail(session, book_id: int, order_index: int) -> LessonDetail:
    lessons = session.query(Lesson).filter_by(book_id=book_id).order_by(Lesson.order_index).all()
    if not lessons:
        raise ValueError(f"No lessons for book {book_id}")

    lesson = next((l for l in lessons if l.order_index == order_index), None)
    if lesson is None:
        raise ValueError(f"No lesson at order_index={order_index} for book {book_id}")

    pos = lessons.index(lesson)
    prev_title = lessons[pos - 1].title if pos > 0 else None
    next_title = lessons[pos + 1].title if pos + 1 < len(lessons) else None

    is_generated = lesson.status == "generated"
    references = (
        [ReferenceView(**r) for r in json.loads(lesson.external_references)]
        if lesson.external_references
        else []
    )
    exercises = (
        [ExerciseView(**e) for e in json.loads(lesson.exercises)] if lesson.exercises else []
    )

    return LessonDetail(
        book_id=book_id,
        order_index=lesson.order_index,
        total_lessons=len(lessons),
        title=lesson.title,
        topic_summary=lesson.topic_summary,
        is_generated=is_generated,
        is_complete=lesson.is_complete,
        content_markdown=lesson.content if is_generated else None,
        references=references,
        exercises=exercises,
        prev_title=prev_title,
        next_title=next_title,
    )


def mark_complete(session, book_id: int, order_index: int) -> LessonDetail:
    mark_lesson_complete(book_id, order_index, session=session)
    return get_lesson_detail(session, book_id, order_index)


def mark_incomplete(session, book_id: int, order_index: int) -> LessonDetail:
    mark_lesson_incomplete(book_id, order_index, session=session)
    return get_lesson_detail(session, book_id, order_index)


def add_book(
    session,
    file_bytes: bytes,
    original_filename: str,
    title: str | None = None,
    books_dir: Path | None = None,
) -> int:
    """Save an uploaded PDF to disk and ingest it. Returns the new book's id."""
    target_dir = books_dir or BOOKS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_path = target_dir / original_filename
    stem, suffix = Path(original_filename).stem, Path(original_filename).suffix
    counter = 1
    while dest_path.exists():
        dest_path = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1

    dest_path.write_bytes(file_bytes)
    report = ingest_book(str(dest_path), title=title, session=session)
    return report.book_id


def mark_plan_generating(session, book_id: int, force: bool = False) -> None:
    """Synchronously flips the Plan row to status="generating" (creating one if
    needed) using the request-scoped session, before the route returns - so the
    very next page load already shows real progress instead of the "Generate
    Plan" button again, rather than waiting for the background task (which now
    runs Chapter Summarization first and could take real minutes before it gets
    around to touching this row itself). Mirrors generate_plan's own
    existing-plan handling (app/generation/plan_generator.py) - only a complete
    plan without force is a real conflict; anything else is just reused.
    """
    existing_plan = session.query(Plan).filter_by(book_id=book_id).one_or_none()

    if existing_plan and existing_plan.status == "complete":
        if not force:
            raise ValueError(
                f"Plan already exists for book {book_id} (plan_id={existing_plan.id}); "
                "pass force=True to regenerate."
            )
        session.delete(existing_plan)
        session.flush()
        existing_plan = None

    if existing_plan:
        existing_plan.status = "generating"
        session.add(existing_plan)
    else:
        session.add(Plan(book_id=book_id, status="generating"))

    session.commit()


def start_plan_generation(book_id: int, force: bool = False) -> None:
    """Entry point for BackgroundTasks - runs after the request/response cycle
    ends, so it owns its own session (generate_plan/summarize_book default to one
    when none is passed) rather than reusing the request-scoped one, which is
    already closed by the time this runs.

    Runs Chapter Summarization first, since Plan Generation reads Chapter.summary
    directly - safe to call unconditionally, as summarize_book already skips any
    chapter that already has a summary, so an already-summarized book costs
    nothing but a quick scan.
    """
    try:
        for _ in summarize_book(book_id):
            pass  # status is persisted per-chapter as summarize_book goes
        generate_plan(book_id, force=force)
    except Exception:
        logger.exception("Plan generation failed for book %s", book_id)
        # Plan.status="failed" is already persisted by generate_plan itself.


def start_lesson_generation(book_id: int) -> None:
    """Entry point for BackgroundTasks - see start_plan_generation for why this
    doesn't take a session."""
    try:
        for _ in generate_book_lessons(book_id):
            pass  # status is persisted per-lesson as generate_book_lessons goes
    except Exception:
        logger.exception("Lesson generation failed for book %s", book_id)


def get_learner_profile_view(session) -> LearnerProfileView:
    profile = session.query(LearnerProfile).filter_by(id=1).one_or_none()
    return LearnerProfileView(
        example_first_vs_theory_first=(profile.example_first_vs_theory_first if profile else None) or "",
        session_length_pref=(profile.session_length_pref if profile else None) or "",
        depth_vs_breadth=(profile.depth_vs_breadth if profile else None) or "",
        tone_pref=(profile.tone_pref if profile else None) or "",
        raw_notes=(profile.raw_notes if profile else None) or "",
    )


def update_learner_profile(
    session,
    example_first_vs_theory_first: str,
    session_length_pref: str,
    depth_vs_breadth: str,
    tone_pref: str,
    raw_notes: str,
) -> LearnerProfileView:
    profile = session.query(LearnerProfile).filter_by(id=1).one_or_none()
    if profile is None:
        profile = LearnerProfile(id=1)
        session.add(profile)

    profile.example_first_vs_theory_first = example_first_vs_theory_first.strip() or None
    profile.session_length_pref = session_length_pref.strip() or None
    profile.depth_vs_breadth = depth_vs_breadth.strip() or None
    profile.tone_pref = tone_pref.strip() or None
    profile.raw_notes = raw_notes.strip() or None

    session.commit()
    return get_learner_profile_view(session)


def get_book_context_view(session, book_id: int) -> BookContextView:
    book = session.query(Book).filter_by(id=book_id).one()
    context = session.query(BookContext).filter_by(book_id=book_id).one_or_none()
    return BookContextView(
        book_id=book.id,
        book_title=book.title,
        goal=(context.goal if context else None) or "",
        prior_familiarity=(context.prior_familiarity if context else None) or "",
        focus_areas=(context.focus_areas if context else None) or "",
        skip_areas=(context.skip_areas if context else None) or "",
    )


def update_book_context(
    session,
    book_id: int,
    goal: str,
    prior_familiarity: str,
    focus_areas: str,
    skip_areas: str,
) -> BookContextView:
    session.query(Book).filter_by(id=book_id).one()  # raises if book doesn't exist

    context = session.query(BookContext).filter_by(book_id=book_id).one_or_none()
    if context is None:
        context = BookContext(book_id=book_id)
        session.add(context)

    context.goal = goal.strip() or None
    context.prior_familiarity = prior_familiarity.strip() or None
    context.focus_areas = focus_areas.strip() or None
    context.skip_areas = skip_areas.strip() or None

    session.commit()
    return get_book_context_view(session, book_id)
