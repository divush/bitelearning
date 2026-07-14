"""Ties together parsing, chapter detection, and chunking, then persists the
result. Entry point used by scripts/ingest_book.py."""

from dataclasses import dataclass
from pathlib import Path

from app.db import get_session
from app.ingestion.chaptering import detect_chapters
from app.ingestion.chunking import chunk_chapter_text
from app.ingestion.pdf_parser import parse_pdf
from app.models import Book, Chapter, Chunk


@dataclass
class ChapterReport:
    order_index: int
    title: str
    start_page: int
    end_page: int
    num_chunks: int


@dataclass
class IngestReport:
    book_id: int
    title: str
    num_pages: int
    chapters: list[ChapterReport]


def ingest_book(path: str, title: str | None = None, session=None) -> IngestReport:
    owns_session = session is None
    if owns_session:
        session = get_session()
    try:
        parsed = parse_pdf(path)
        book_title = title or Path(path).stem

        book = Book(
            title=book_title,
            source_filename=Path(path).name,
            num_pages=parsed.num_pages,
            status="parsing",
        )
        session.add(book)
        session.flush()  # assign book.id

        detected_chapters = detect_chapters(parsed)

        chapter_reports = []
        for dc in detected_chapters:
            chapter_text = "\n\n".join(parsed.pages[dc.start_page : dc.end_page + 1])

            chapter = Chapter(
                book_id=book.id,
                order_index=dc.order_index,
                title=dc.title,
                start_page=dc.start_page,
                end_page=dc.end_page,
            )
            session.add(chapter)
            session.flush()  # assign chapter.id

            chunks = chunk_chapter_text(chapter_text)
            for i, chunk in enumerate(chunks):
                session.add(
                    Chunk(
                        chapter_id=chapter.id,
                        order_index=i,
                        token_count=chunk.token_count,
                        text=chunk.text,
                    )
                )

            chapter_reports.append(
                ChapterReport(
                    order_index=dc.order_index,
                    title=dc.title,
                    start_page=dc.start_page,
                    end_page=dc.end_page,
                    num_chunks=len(chunks),
                )
            )

        book.status = "parsed"
        session.commit()

        return IngestReport(
            book_id=book.id,
            title=book.title,
            num_pages=parsed.num_pages,
            chapters=chapter_reports,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
