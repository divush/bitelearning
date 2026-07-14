"""Chapter summarization: produces a rolling, per-chapter digest so later
generation steps (Plan, Lesson) can be aware of the whole book without
re-reading every chunk. See app/ingestion for how chapters/chunks are produced.
"""

from collections.abc import Iterator
from typing import NamedTuple

from langchain_core.prompts import ChatPromptTemplate

from app.config import SUMMARY_MAP_BATCH_TOKENS, SUMMARY_MODEL
from app.db import get_session
from app.llm import get_chat_model
from app.models import Chapter, Chunk

NO_PRIOR_CONTEXT = "(this is the first chapter; there is no prior context)"

SINGLE_CALL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are helping build a structured, chapter-by-chapter digest of a "
            "non-fiction book for a personal learning tool. Summarize the chapter "
            "below in 150-300 words: cover the main topics/concepts it introduces, "
            "and explicitly note how it builds on or relates to the prior chapters "
            "(given below as context). Do not restate prior content at length - "
            "focus on what's new in this chapter.",
        ),
        (
            "human",
            "Chapter title: {title}\n\n"
            "Prior chapters covered so far:\n{prior_context}\n\n"
            "Full text of this chapter:\n{chapter_text}",
        ),
    ]
)

MAP_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Summarize the following excerpt from a book chapter faithfully and "
            "concisely (~150 words), preserving key concepts, terms, and important "
            "details. This is a partial excerpt from a larger chapter - do not try "
            "to conclude the chapter or add material that isn't present.",
        ),
        (
            "human",
            "Chapter title: {title}\nExcerpt {part_index} of {part_count}:\n\n{excerpt}",
        ),
    ]
)

REDUCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are helping build a structured, chapter-by-chapter digest of a "
            "non-fiction book for a personal learning tool. Below are summaries of "
            "consecutive excerpts of one chapter. Combine them into a single "
            "coherent chapter summary (150-300 words) that covers the main topics/"
            "concepts introduced, and explicitly notes how this chapter builds on "
            "or relates to the prior chapters (given below as context).",
        ),
        (
            "human",
            "Chapter title: {title}\n\n"
            "Prior chapters covered so far:\n{prior_context}\n\n"
            "Excerpt summaries for this chapter, in order:\n{batch_summaries}",
        ),
    ]
)


def batch_chunks(chunks: list[Chunk], max_tokens: int) -> list[list[Chunk]]:
    ordered = sorted(chunks, key=lambda c: c.order_index)
    batches: list[list[Chunk]] = []
    current: list[Chunk] = []
    current_tokens = 0

    for chunk in ordered:
        if current and current_tokens + chunk.token_count > max_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(chunk)
        current_tokens += chunk.token_count

    if current:
        batches.append(current)

    return batches


def _batch_text(batch: list[Chunk]) -> str:
    return "\n\n".join(c.text for c in sorted(batch, key=lambda c: c.order_index))


def summarize_chapter(
    title: str,
    chunks: list[Chunk],
    prior_context: str,
    model,
    max_batch_tokens: int = SUMMARY_MAP_BATCH_TOKENS,
) -> str:
    if not chunks:
        return ""

    prior_context_text = prior_context.strip() or NO_PRIOR_CONTEXT
    batches = batch_chunks(chunks, max_batch_tokens)

    if len(batches) == 1:
        messages = SINGLE_CALL_PROMPT.format_messages(
            title=title,
            prior_context=prior_context_text,
            chapter_text=_batch_text(batches[0]),
        )
        return model.invoke(messages).content.strip()

    batch_summaries = []
    for i, batch in enumerate(batches):
        messages = MAP_PROMPT.format_messages(
            title=title,
            part_index=i + 1,
            part_count=len(batches),
            excerpt=_batch_text(batch),
        )
        batch_summaries.append(model.invoke(messages).content.strip())

    combined = "\n\n".join(f"[Part {i + 1}]\n{s}" for i, s in enumerate(batch_summaries))
    messages = REDUCE_PROMPT.format_messages(
        title=title,
        prior_context=prior_context_text,
        batch_summaries=combined,
    )
    return model.invoke(messages).content.strip()


class ChapterSummaryResult(NamedTuple):
    chapter: Chapter
    status: str  # "skipped_empty" / "skipped_existing" / "generated"


def summarize_book(
    book_id: int,
    force: bool = False,
    model=None,
    session=None,
) -> Iterator[ChapterSummaryResult]:
    owns_session = session is None
    if owns_session:
        session = get_session()
    model = model or get_chat_model(SUMMARY_MODEL)

    try:
        chapters = (
            session.query(Chapter)
            .filter_by(book_id=book_id)
            .order_by(Chapter.order_index)
            .all()
        )

        prior_summaries: list[str] = []

        for chapter in chapters:
            chunks = (
                session.query(Chunk)
                .filter_by(chapter_id=chapter.id)
                .order_by(Chunk.order_index)
                .all()
            )

            if not chunks:
                yield ChapterSummaryResult(chapter, "skipped_empty")
                continue

            if chapter.summary and not force:
                prior_summaries.append(f"{chapter.title}: {chapter.summary}")
                yield ChapterSummaryResult(chapter, "skipped_existing")
                continue

            prior_context = "\n\n".join(prior_summaries)
            summary = summarize_chapter(chapter.title, chunks, prior_context, model)

            chapter.summary = summary
            session.add(chapter)
            session.commit()

            prior_summaries.append(f"{chapter.title}: {summary}")
            yield ChapterSummaryResult(chapter, "generated")
    finally:
        if owns_session:
            session.close()
