"""Lesson Generation: writes the full self-contained content for each lesson stub
produced by Plan Generation - core explanation, external references (via search),
and practice exercises where the material lends itself to that.

The only module so far that needs LangGraph: a 3-node research-then-write graph
(agent -> tools -> agent ... -> compose) so the model can decide whether external
material would help, search for it, and only then write the final structured lesson.
"""

import json
from typing import Iterator, NamedTuple

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from app.config import LESSON_COMPOSE_MODEL, LESSON_GRAPH_RECURSION_LIMIT, LESSON_RESEARCH_MODEL
from app.db import get_session
from app.generation.profile_context_format import format_context, format_profile
from app.llm import get_chat_model
from app.models import BookContext, Chapter, Chunk, LearnerProfile, Lesson, Plan
from app.tools.search import web_search


class ExternalReference(BaseModel):
    title: str
    url: str
    why_relevant: str = Field(description="Why this reference is worth including for this lesson")


class Exercise(BaseModel):
    prompt: str
    guidance: str | None = Field(
        default=None, description="An optional hint or approach - not a full answer key"
    )


class LessonContent(BaseModel):
    core_content: str = Field(description="Self-contained lesson body, in markdown")
    references: list[ExternalReference] = Field(default_factory=list)
    exercises: list[Exercise] = Field(default_factory=list)


class LessonGraphState(MessagesState):
    final_content: LessonContent | None


class LessonGenerationResult(NamedTuple):
    lesson: Lesson
    status: str  # "skipped_existing" / "generated" / "failed"
    error: str | None = None


SYSTEM_PROMPT = (
    "You are writing one self-contained lesson for a personalized learning tool, as one item "
    "in an ordered curriculum for a book. Before writing the final lesson, you may use the "
    "web_search tool to find real-world case studies, canonical papers/tools, or notable "
    "production incidents that would meaningfully enrich the lesson - but only if the book's "
    "own material isn't already sufficient. Call it zero, one, or a few times as needed, then "
    "stop calling tools once you're ready to write.\n\n"
    "The lesson must be self-contained: readable on its own, days after the previous lesson, "
    "with enough restated context that the reader doesn't need to flip back. Do not repeat "
    "material already covered by earlier lessons (listed below) at length - build on it instead. "
    "Include practice exercises only where the material genuinely lends itself to that."
)

COMPOSE_INSTRUCTION = (
    "Based on everything above (the brief, context, and any search results), write the final "
    "self-contained lesson now."
)


def build_context_messages(
    lesson: Lesson,
    source_chunks_text: str,
    chapter_summaries_text: str,
    prior_lesson_summaries_text: str,
    profile: LearnerProfile | None,
    context: BookContext | None,
) -> list[BaseMessage]:
    human = HumanMessage(
        content=(
            f"Learner profile:\n{format_profile(profile)}\n\n"
            f"Book context:\n{format_context(context)}\n\n"
            f"This lesson's brief:\nTitle: {lesson.title}\nWhat it should cover: {lesson.topic_summary}\n\n"
            f"Earlier lessons already taught in this plan (do not repeat at length):\n"
            f"{prior_lesson_summaries_text}\n\n"
            f"Whole-book chapter summaries (for context):\n{chapter_summaries_text}\n\n"
            f"Full source text for this lesson (draw the core explanation from this):\n"
            f"{source_chunks_text}"
        )
    )
    return [SystemMessage(content=SYSTEM_PROMPT), human]


def build_lesson_graph(research_model, compose_model, search_tool):
    research_model_with_tools = research_model.bind_tools([search_tool])
    compose_structured_model = compose_model.with_structured_output(LessonContent)

    def agent_node(state: LessonGraphState) -> dict:
        response = research_model_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def compose_node(state: LessonGraphState) -> dict:
        instruction = HumanMessage(content=COMPOSE_INSTRUCTION)
        result = compose_structured_model.invoke(state["messages"] + [instruction])
        return {"final_content": result}

    graph = StateGraph(LessonGraphState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode([search_tool]))
    graph.add_node("compose", compose_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "compose"})
    graph.add_edge("tools", "agent")
    graph.add_edge("compose", END)

    return graph.compile()


def generate_lesson(
    lesson: Lesson,
    source_chunks_text: str,
    chapter_summaries_text: str,
    prior_lesson_summaries_text: str,
    profile: LearnerProfile | None,
    context: BookContext | None,
    graph=None,
) -> LessonContent:
    if graph is None:
        research_model = get_chat_model(LESSON_RESEARCH_MODEL)
        compose_model = get_chat_model(LESSON_COMPOSE_MODEL)
        graph = build_lesson_graph(research_model, compose_model, web_search)

    messages = build_context_messages(
        lesson, source_chunks_text, chapter_summaries_text, prior_lesson_summaries_text, profile, context
    )

    final_state = graph.invoke(
        {"messages": messages, "final_content": None},
        config={"recursion_limit": LESSON_GRAPH_RECURSION_LIMIT},
    )
    return final_state["final_content"]


def _build_source_chunks_text(session, chapter_ids: list[int], chapters_by_id: dict[int, Chapter]) -> str:
    parts = []
    for cid in chapter_ids:
        chapter = chapters_by_id.get(cid)
        if chapter is None:
            continue
        chunks = session.query(Chunk).filter_by(chapter_id=cid).order_by(Chunk.order_index).all()
        chapter_text = "\n\n".join(c.text for c in chunks)
        parts.append(f"=== {chapter.title} ===\n{chapter_text}")
    return "\n\n".join(parts)


def generate_book_lessons(
    book_id: int,
    force: bool = False,
    lesson_index: int | None = None,
    graph=None,
    session=None,
) -> Iterator[LessonGenerationResult]:
    """If lesson_index is given, only that lesson (by order_index) is generated -
    others are skipped, though their topic_summary still feeds prior-lesson context
    for continuity."""
    owns_session = session is None
    if owns_session:
        session = get_session()

    try:
        plan = session.query(Plan).filter_by(book_id=book_id).one_or_none()
        if plan is None:
            raise ValueError(f"No plan exists for book {book_id}; run generate_plan first.")

        lessons = (
            session.query(Lesson).filter_by(plan_id=plan.id).order_by(Lesson.order_index).all()
        )

        chapters = (
            session.query(Chapter).filter_by(book_id=book_id).order_by(Chapter.order_index).all()
        )
        chapter_summaries_text = "\n\n".join(f"{c.title}: {c.summary}" for c in chapters if c.summary)
        chapters_by_id = {c.id: c for c in chapters}

        profile = session.query(LearnerProfile).filter_by(id=1).one_or_none()
        context = session.query(BookContext).filter_by(book_id=book_id).one_or_none()

        prior_lesson_summaries: list[str] = []

        for lesson in lessons:
            if lesson_index is not None and lesson.order_index != lesson_index:
                prior_lesson_summaries.append(f"{lesson.title}: {lesson.topic_summary}")
                continue

            if lesson.status == "generated" and not force:
                prior_lesson_summaries.append(f"{lesson.title}: {lesson.topic_summary}")
                yield LessonGenerationResult(lesson, "skipped_existing")
                continue

            try:
                # Committed before the slow generation call so a concurrent reader
                # (e.g. the web UI polling for progress) can see which lesson is
                # currently in flight rather than just a stale "planned" status.
                lesson.status = "generating"
                session.add(lesson)
                session.commit()

                source_chapter_ids = json.loads(lesson.source_chapter_ids)
                source_chunks_text = _build_source_chunks_text(session, source_chapter_ids, chapters_by_id)
                prior_text = "\n\n".join(prior_lesson_summaries) or "(none - this is the first lesson)"

                content = generate_lesson(
                    lesson,
                    source_chunks_text,
                    chapter_summaries_text,
                    prior_text,
                    profile,
                    context,
                    graph=graph,
                )

                lesson.content = content.core_content
                lesson.external_references = json.dumps([r.model_dump() for r in content.references])
                lesson.exercises = json.dumps([e.model_dump() for e in content.exercises])
                lesson.status = "generated"
                session.add(lesson)
                session.commit()

                prior_lesson_summaries.append(f"{lesson.title}: {lesson.topic_summary}")
                yield LessonGenerationResult(lesson, "generated")
            except Exception as e:
                session.rollback()
                lesson.status = "failed"
                session.add(lesson)
                session.commit()

                prior_lesson_summaries.append(f"{lesson.title}: {lesson.topic_summary}")
                yield LessonGenerationResult(lesson, "failed", error=str(e))
    finally:
        if owns_session:
            session.close()
