import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.generation.summarizer import batch_chunks, summarize_book, summarize_chapter
from app.models import Base, Book, Chapter, Chunk


class _StubResponse:
    def __init__(self, content: str):
        self.content = content


class _StubChatModel:
    """Swapped in for a real ChatOpenAI so tests never hit the network."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[object] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _StubResponse(self.responses.pop(0))


def _make_chunk(order_index: int, token_count: int) -> Chunk:
    return Chunk(order_index=order_index, token_count=token_count, text=f"chunk-{order_index} text")


def test_batch_chunks_respects_budget_and_preserves_order():
    # fed in scrambled order on purpose
    chunks = [_make_chunk(i, 300) for i in (2, 0, 4, 1, 3)]

    batches = batch_chunks(chunks, max_tokens=700)

    assert [c.order_index for c in batches[0]] == [0, 1]
    assert [c.order_index for c in batches[1]] == [2, 3]
    assert [c.order_index for c in batches[2]] == [4]


def test_summarize_chapter_single_batch_makes_one_call():
    chunks = [_make_chunk(0, 100), _make_chunk(1, 100)]
    stub = _StubChatModel(responses=["The chapter summary."])

    result = summarize_chapter("Chapter 1", chunks, prior_context="", model=stub, max_batch_tokens=10_000)

    assert result == "The chapter summary."
    assert len(stub.calls) == 1


def test_summarize_chapter_map_reduce_fallback_when_over_budget():
    chunks = [_make_chunk(i, 100) for i in range(4)]
    # budget forces 2 chunks per batch -> 2 map calls + 1 reduce call
    stub = _StubChatModel(responses=["batch summary 1", "batch summary 2", "final chapter summary"])

    result = summarize_chapter("Chapter 1", chunks, prior_context="prior stuff", model=stub, max_batch_tokens=200)

    assert result == "final chapter summary"
    assert len(stub.calls) == 3


def test_summarize_chapter_empty_chunks_returns_empty_string():
    stub = _StubChatModel(responses=[])
    result = summarize_chapter("Empty Chapter", [], prior_context="", model=stub)
    assert result == ""
    assert stub.calls == []


def _make_test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_summarize_book_persists_summaries_and_is_resumable():
    session = _make_test_session()
    book = Book(title="Test Book", source_filename="test.pdf", num_pages=10, status="parsed")
    session.add(book)
    session.flush()

    ch1 = Chapter(book_id=book.id, order_index=0, title="Chapter 1", start_page=0, end_page=4)
    ch2 = Chapter(book_id=book.id, order_index=1, title="Chapter 2", start_page=5, end_page=9)
    empty_ch = Chapter(book_id=book.id, order_index=2, title="Blank Page", start_page=10, end_page=10)
    session.add_all([ch1, ch2, empty_ch])
    session.flush()

    session.add(Chunk(chapter_id=ch1.id, order_index=0, token_count=50, text="ch1 text"))
    session.add(Chunk(chapter_id=ch2.id, order_index=0, token_count=50, text="ch2 text"))
    session.commit()

    stub = _StubChatModel(responses=["summary for ch1", "summary for ch2"])
    results = list(summarize_book(book.id, model=stub, session=session))

    statuses = {r.chapter.title: r.status for r in results}
    assert statuses == {
        "Chapter 1": "generated",
        "Chapter 2": "generated",
        "Blank Page": "skipped_empty",
    }
    assert ch1.summary == "summary for ch1"
    assert ch2.summary == "summary for ch2"
    assert len(stub.calls) == 2

    # re-run without --force: should skip both already-summarized chapters, no new LLM calls
    stub_2 = _StubChatModel(responses=[])
    results_2 = list(summarize_book(book.id, model=stub_2, session=session))
    statuses_2 = {r.chapter.title: r.status for r in results_2}
    assert statuses_2 == {
        "Chapter 1": "skipped_existing",
        "Chapter 2": "skipped_existing",
        "Blank Page": "skipped_empty",
    }
    assert stub_2.calls == []

    # force=True: should regenerate
    stub_3 = _StubChatModel(responses=["new summary for ch1", "new summary for ch2"])
    results_3 = list(summarize_book(book.id, force=True, model=stub_3, session=session))
    statuses_3 = {r.chapter.title: r.status for r in results_3}
    assert statuses_3 == {
        "Chapter 1": "generated",
        "Chapter 2": "generated",
        "Blank Page": "skipped_empty",
    }
    assert ch1.summary == "new summary for ch1"
    assert ch2.summary == "new summary for ch2"
