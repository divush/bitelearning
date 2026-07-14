"""Plan Generation: decides what to teach and in what order, before any lesson
content is written. Input: chapter summaries + Learner Profile + Book Context.
Output: an ordered list of lesson stubs, persisted as Plan + Lesson rows.
"""

import json
from typing import NamedTuple

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.config import MIN_CHUNKS_FOR_LESSON_CANDIDACY, PLAN_MODEL
from app.db import get_session
from app.generation.profile_context_format import format_context, format_profile
from app.llm import get_chat_model
from app.models import Book, BookContext, Chapter, Chunk, LearnerProfile, Lesson, Plan


class LessonStub(BaseModel):
    title: str = Field(description="Short, specific lesson title")
    topic_summary: str = Field(
        description="2-4 sentences on what this lesson will cover and why it matters here - "
        "used later to guide the actual lesson-writing step"
    )
    source_chapter_ids: list[int] = Field(
        min_length=1,
        description="IDs of the book's candidate chapters this lesson primarily draws from, "
        "in relevance order",
    )


class BookPlan(BaseModel):
    lessons: list[LessonStub]


class ChapterWithCount(NamedTuple):
    chapter: Chapter
    chunk_count: int


PLAN_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are designing a personalized, ordered curriculum (a sequence of lessons) to "
            "teach a specific book to one learner, based on their standing learning-style "
            "profile and their stated goals for this particular book.\n\n"
            "You will be given: the learner's profile, their context/goals for this book, a "
            "list of candidate chapters (each with an id, title, and summary) that lessons may "
            "be built from, and a list of other book sections shown only for structural context "
            "(front matter, part dividers) that must NOT become lessons themselves.\n\n"
            "Decide an ordered list of lessons that together cover the book (or the relevant "
            "parts of it, per the learner's stated context). You may merge multiple short/"
            "related candidate chapters into a single lesson, split a long or dense chapter "
            "into multiple lessons, reorder chapters if there's a good pedagogical reason, and "
            "skip material the learner said to skip or already knows well. Match the "
            "granularity and depth to the learner's stated preferences (e.g. a breadth "
            "preference should yield fewer, broader lessons; a depth preference should yield "
            "more, narrower ones).\n\n"
            "Each lesson needs a specific, concrete title (not just a copy of a chapter title) "
            "and a topic_summary describing what that lesson will actually cover and why it's "
            "placed there. Each lesson's source_chapter_ids must reference only ids from the "
            "candidate chapter list below - never invent ids and never reference the "
            "context-only sections.",
        ),
        (
            "human",
            "Learner profile:\n{profile_text}\n\n"
            "Book context:\n{context_text}\n\n"
            "Candidate chapters:\n{candidates_text}\n\n"
            "Other book sections (context only, do not create lessons for these):\n"
            "{context_only_text}",
        ),
    ]
)


def split_candidate_chapters(
    chapters_with_counts: list[ChapterWithCount],
    min_chunks: int,
) -> tuple[list[ChapterWithCount], list[ChapterWithCount]]:
    candidates = [c for c in chapters_with_counts if c.chunk_count >= min_chunks]
    context_only = [c for c in chapters_with_counts if c.chunk_count < min_chunks]
    return candidates, context_only


def _format_candidates(candidates: list[ChapterWithCount]) -> str:
    return "\n".join(f"- [id={c.chapter.id}] {c.chapter.title}: {c.chapter.summary}" for c in candidates)


def _format_context_only(context_only: list[ChapterWithCount]) -> str:
    if not context_only:
        return "(none)"
    return "\n".join(f"- {c.chapter.title}" for c in context_only)


def generate_plan(
    book_id: int,
    force: bool = False,
    model=None,
    session=None,
) -> Plan:
    owns_session = session is None
    if owns_session:
        session = get_session()
    model = model or get_chat_model(PLAN_MODEL).with_structured_output(BookPlan)

    try:
        session.query(Book).filter_by(id=book_id).one()  # raises if book doesn't exist

        existing_plan = session.query(Plan).filter_by(book_id=book_id).one_or_none()
        if existing_plan and not force:
            raise ValueError(
                f"Plan already exists for book {book_id} (plan_id={existing_plan.id}); "
                "pass force=True to regenerate."
            )
        if existing_plan and force:
            session.delete(existing_plan)
            session.flush()

        # Created and committed up front (before the slow LLM call) so a concurrent
        # reader - e.g. the web UI polling for progress - can see generation is in
        # flight rather than finding no row at all until it's done.
        plan = Plan(book_id=book_id, status="generating")
        session.add(plan)
        session.commit()

        try:
            chapters = (
                session.query(Chapter)
                .filter_by(book_id=book_id)
                .order_by(Chapter.order_index)
                .all()
            )
            chapters_with_counts = [
                ChapterWithCount(
                    chapter=ch,
                    chunk_count=session.query(Chunk).filter_by(chapter_id=ch.id).count(),
                )
                for ch in chapters
            ]

            candidates, context_only = split_candidate_chapters(
                chapters_with_counts, MIN_CHUNKS_FOR_LESSON_CANDIDACY
            )

            profile = session.query(LearnerProfile).filter_by(id=1).one_or_none()
            context = session.query(BookContext).filter_by(book_id=book_id).one_or_none()

            messages = PLAN_PROMPT.format_messages(
                profile_text=format_profile(profile),
                context_text=format_context(context),
                candidates_text=_format_candidates(candidates),
                context_only_text=_format_context_only(context_only),
            )

            book_plan: BookPlan = model.invoke(messages)

            for i, stub in enumerate(book_plan.lessons):
                session.add(
                    Lesson(
                        plan_id=plan.id,
                        book_id=book_id,
                        order_index=i,
                        title=stub.title,
                        topic_summary=stub.topic_summary,
                        source_chapter_ids=json.dumps(stub.source_chapter_ids),
                        status="planned",
                    )
                )

            plan.status = "complete"
            session.commit()
            return plan
        except Exception:
            session.rollback()
            plan.status = "failed"
            session.add(plan)
            session.commit()
            raise
    finally:
        if owns_session:
            session.close()
