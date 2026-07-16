"""Plain data-transfer objects returned by the service layer. Never ORM instances -
this is what keeps the web layer from touching app.models/app.db directly. Rendering
transforms (e.g. markdown -> HTML) are a presentation concern and deliberately do NOT
happen here; content_markdown stays raw markdown for the web layer to render.
"""

from dataclasses import dataclass


@dataclass
class BookSummary:
    id: int
    title: str
    total_lessons: int
    completed_count: int


@dataclass
class PlanLessonRow:
    order_index: int
    title: str
    is_complete: bool
    is_generated: bool
    is_generating: bool
    is_failed: bool


@dataclass
class BookWorkspace:
    book_id: int
    title: str
    num_pages: int
    total_lessons: int
    completed_count: int
    lessons: list[PlanLessonRow]
    plan_status: str | None  # None | "generating" | "complete" | "failed"
    plan_elapsed_display: str | None  # e.g. "14s" / "1m 12s", only while plan_status == "generating"
    lessons_generating: bool
    generated_count: int
    current_lesson_title: str | None  # title of the lesson currently mid-generation, if any
    chapters_total: int  # chapters with at least one chunk (i.e. eligible for summarization)
    chapters_summarized: int
    summarizing_chapters: bool  # true while plan generation is running and not all chapters are summarized yet


@dataclass
class ReferenceView:
    title: str
    url: str
    why_relevant: str


@dataclass
class ExerciseView:
    prompt: str
    guidance: str | None


@dataclass
class LessonDetail:
    book_id: int
    order_index: int
    total_lessons: int
    title: str
    topic_summary: str
    is_generated: bool
    is_complete: bool
    content_markdown: str | None
    references: list[ReferenceView]
    exercises: list[ExerciseView]
    prev_title: str | None
    next_title: str | None


@dataclass
class LearnerProfileView:
    example_first_vs_theory_first: str
    session_length_pref: str
    depth_vs_breadth: str
    tone_pref: str
    raw_notes: str


@dataclass
class BookContextView:
    book_id: int
    book_title: str
    goal: str
    prior_familiarity: str
    focus_areas: str
    skip_areas: str
