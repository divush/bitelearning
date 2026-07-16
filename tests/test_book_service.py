import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import book_service


def test_start_plan_generation_summarizes_before_planning(monkeypatch):
    calls = []

    def stub_summarize(book_id):
        calls.append(("summarize", book_id))
        return iter([])  # generate_plan's driving loop just needs something iterable

    monkeypatch.setattr(book_service, "summarize_book", stub_summarize)
    monkeypatch.setattr(
        book_service,
        "generate_plan",
        lambda book_id, force=False: calls.append(("plan", book_id, force)),
    )

    book_service.start_plan_generation(42, force=True)

    assert calls == [("summarize", 42), ("plan", 42, True)]


def test_start_plan_generation_skips_plan_if_summarization_fails(monkeypatch):
    def failing_summarize(book_id):
        raise RuntimeError("simulated summarization failure")

    calls = []
    monkeypatch.setattr(book_service, "summarize_book", failing_summarize)
    monkeypatch.setattr(book_service, "generate_plan", lambda book_id, force=False: calls.append("plan"))

    book_service.start_plan_generation(1)  # must not raise - caught and logged internally

    assert calls == []
