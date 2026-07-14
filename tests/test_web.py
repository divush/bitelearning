import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Book, Lesson, Plan
from app.services import book_service
from app.services.session import get_db
from app.web.app import app


def _make_minimal_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1\n\nHello world, this is a test book.")
    doc.save(str(path))
    doc.close()


def _make_test_session():
    # StaticPool + check_same_thread=False: TestClient runs routes in a worker
    # thread, and SQLite's default per-thread pooling would otherwise hand that
    # thread a separate, empty :memory: database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session):
    book = Book(
        title="Designing Data-Intensive Applications",
        source_filename="ddia.pdf",
        num_pages=491,
        status="parsed",
    )
    session.add(book)
    session.flush()

    plan = Plan(book_id=book.id, status="complete")
    session.add(plan)
    session.flush()

    lesson0 = Lesson(
        plan_id=plan.id,
        book_id=book.id,
        order_index=0,
        title="The Core Challenges",
        topic_summary="Why reliability, scalability, and maintainability matter.",
        content="# The Core Challenges\n\nSome **content** here.",
        external_references=json.dumps(
            [{"title": "Ref A", "url": "https://example.com/a", "why_relevant": "because"}]
        ),
        exercises=json.dumps([{"prompt": "Do X", "guidance": "Think about Y"}]),
        status="generated",
        is_complete=False,
    )
    lesson1 = Lesson(
        plan_id=plan.id,
        book_id=book.id,
        order_index=1,
        title="How Data Shapes Systems",
        topic_summary="Data models matter.",
        content="# Data Models\n\nMore content.",
        external_references="[]",
        exercises="[]",
        status="generated",
        is_complete=True,
    )
    session.add_all([lesson0, lesson1])
    session.commit()
    return book


def _make_book(session, title, num_pages=10):
    book = Book(title=title, source_filename=f"{title}.pdf", num_pages=num_pages, status="parsed")
    session.add(book)
    session.flush()
    return book


test_session = _make_test_session()
book = _seed(test_session)


def _override_get_db():
    yield test_session


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def test_index_redirects_to_first_book():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert response.headers["location"] == f"/books/{book.id}"


def test_plan_page_renders_lessons_and_progress():
    response = client.get(f"/books/{book.id}")
    assert response.status_code == 200
    body = response.text
    assert "The Core Challenges" in body
    assert "How Data Shapes Systems" in body
    assert "1 of 2 lessons complete" in body


def test_reader_page_renders_content_references_and_exercises():
    response = client.get(f"/books/{book.id}/lessons/0")
    assert response.status_code == 200
    body = response.text
    assert "Some" in body and "content" in body
    assert "Ref A" in body
    assert "Do X" in body
    assert "Mark as completed" in body


def test_reader_page_shows_completed_state():
    response = client.get(f"/books/{book.id}/lessons/1")
    assert "Completed" in response.text


def test_mark_complete_endpoint_toggles_state_and_persists():
    response = client.post(f"/books/{book.id}/lessons/0/complete")
    assert response.status_code == 200
    assert "Completed" in response.text

    followup = client.get(f"/books/{book.id}/lessons/0")
    assert "Completed" in followup.text

    undo = client.post(f"/books/{book.id}/lessons/0/incomplete")
    assert "Mark as completed" in undo.text


def test_lesson_not_found_returns_404():
    response = client.get(f"/books/{book.id}/lessons/99")
    assert response.status_code == 404


def test_book_not_found_returns_404():
    response = client.get("/books/9999")
    assert response.status_code == 404


def test_new_book_form_renders():
    response = client.get("/books/new")
    assert response.status_code == 200
    assert 'type="file"' in response.text


def test_add_book_ingests_real_pdf_and_redirects(tmp_path):
    pdf_path = tmp_path / "test-book.pdf"
    _make_minimal_pdf(pdf_path)
    books_dir = tmp_path / "books_storage"

    app.dependency_overrides[book_service.get_books_dir] = lambda: books_dir
    try:
        with open(pdf_path, "rb") as f:
            response = client.post(
                "/books",
                files={"pdf": ("test-book.pdf", f, "application/pdf")},
                data={"title": "My Test Book"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        location = response.headers["location"]

        check = client.get(location)
        assert check.status_code == 200
        assert "My Test Book" in check.text

        saved_files = list(books_dir.glob("*.pdf"))
        assert len(saved_files) == 1
    finally:
        del app.dependency_overrides[book_service.get_books_dir]


def test_add_book_rejects_non_pdf():
    response = client.post(
        "/books",
        files={"pdf": ("notes.txt", b"just some text", "text/plain")},
        data={"title": ""},
    )
    assert response.status_code == 400
    assert "Please choose a PDF file" in response.text


def test_add_book_avoids_filename_collision(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    _make_minimal_pdf(pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    books_dir = tmp_path / "books"

    book_id_1 = book_service.add_book(test_session, pdf_bytes, "same-name.pdf", books_dir=books_dir)
    book_id_2 = book_service.add_book(test_session, pdf_bytes, "same-name.pdf", books_dir=books_dir)

    assert book_id_1 != book_id_2
    saved = sorted(p.name for p in books_dir.glob("*.pdf"))
    assert saved == ["same-name-1.pdf", "same-name.pdf"]


def test_plan_page_shows_generate_plan_button_when_no_plan_exists():
    b = _make_book(test_session, "No Plan Yet Book")
    test_session.commit()

    response = client.get(f"/books/{b.id}")
    assert response.status_code == 200
    assert "Generate Plan" in response.text


def test_trigger_plan_generation_calls_service_and_redirects(monkeypatch):
    b = _make_book(test_session, "Trigger Plan Book")
    test_session.commit()

    calls = []
    monkeypatch.setattr(
        book_service, "start_plan_generation", lambda book_id, force=False: calls.append((book_id, force))
    )

    response = client.post(f"/books/{b.id}/plan", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{b.id}"
    assert calls == [(b.id, False)]


def test_trigger_plan_generation_passes_force_flag(monkeypatch):
    b = _make_book(test_session, "Trigger Plan Force Book")
    test_session.commit()

    calls = []
    monkeypatch.setattr(
        book_service, "start_plan_generation", lambda book_id, force=False: calls.append((book_id, force))
    )

    client.post(f"/books/{b.id}/plan?force=true")
    assert calls == [(b.id, True)]


def test_trigger_lesson_generation_calls_service_and_redirects(monkeypatch):
    b = _make_book(test_session, "Trigger Lessons Book")
    test_session.add(Plan(book_id=b.id, status="complete"))
    test_session.commit()

    calls = []
    monkeypatch.setattr(book_service, "start_lesson_generation", lambda book_id: calls.append(book_id))

    response = client.post(f"/books/{b.id}/lessons/generate", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{b.id}"
    assert calls == [b.id]


def test_status_endpoint_shows_generating_plan_message():
    b = _make_book(test_session, "Status Generating Plan Book")
    test_session.add(Plan(book_id=b.id, status="generating"))
    test_session.commit()

    response = client.get(f"/books/{b.id}/status")
    assert "Generating plan" in response.text
    assert 'hx-trigger="every 3s"' in response.text
    assert 'class="spinner"' in response.text
    assert re.search(r"\(\d+s\)|\(\d+m \d+s\)", response.text)


def test_status_endpoint_shows_failed_plan_and_retry_button():
    b = _make_book(test_session, "Status Failed Plan Book")
    test_session.add(Plan(book_id=b.id, status="failed"))
    test_session.commit()

    response = client.get(f"/books/{b.id}/status")
    assert "Plan generation failed" in response.text
    assert "Retry" in response.text


def test_status_endpoint_shows_generate_lessons_button_when_plan_complete_and_ungenerated():
    b = _make_book(test_session, "Status Ready For Lessons Book")
    plan = Plan(book_id=b.id, status="complete")
    test_session.add(plan)
    test_session.flush()
    test_session.add(
        Lesson(plan_id=plan.id, book_id=b.id, order_index=0, title="L1", topic_summary="x", status="planned")
    )
    test_session.commit()

    response = client.get(f"/books/{b.id}/status")
    assert "Generate Lessons" in response.text


def test_status_endpoint_shows_generating_lessons_progress():
    b = _make_book(test_session, "Status Generating Lessons Book")
    plan = Plan(book_id=b.id, status="complete")
    test_session.add(plan)
    test_session.flush()
    test_session.add(
        Lesson(plan_id=plan.id, book_id=b.id, order_index=0, title="L1", topic_summary="x", status="generating")
    )
    test_session.add(
        Lesson(plan_id=plan.id, book_id=b.id, order_index=1, title="L2", topic_summary="y", status="planned")
    )
    test_session.commit()

    response = client.get(f"/books/{b.id}/status")
    assert "Generating lessons" in response.text
    assert "0 of 2 done" in response.text
    assert "currently: <em>L1</em>" in response.text
    assert 'class="generation-progress"' in response.text


def test_plan_page_marks_failed_lesson_distinctly():
    b = _make_book(test_session, "Status Failed Lesson Book")
    plan = Plan(book_id=b.id, status="complete")
    test_session.add(plan)
    test_session.flush()
    test_session.add(
        Lesson(plan_id=plan.id, book_id=b.id, order_index=0, title="Broken Lesson", topic_summary="x", status="failed")
    )
    test_session.commit()

    response = client.get(f"/books/{b.id}")
    assert 'status-chip failed' in response.text
    assert "(failed)" in response.text


def test_profile_form_renders_with_empty_defaults():
    response = client.get("/profile")
    assert response.status_code == 200
    assert 'name="raw_notes"' in response.text


def test_profile_update_persists_and_shows_saved():
    response = client.post(
        "/profile",
        data={
            "example_first_vs_theory_first": "Wants motivation before mechanics",
            "session_length_pref": "25 minutes",
            "depth_vs_breadth": "High depth",
            "tone_pref": "Direct",
            "raw_notes": "Prefers narrative structure",
        },
    )
    assert response.status_code == 200
    assert "Saved." in response.text
    assert "Wants motivation before mechanics" in response.text

    followup = client.get("/profile")
    assert "25 minutes" in followup.text
    assert "Prefers narrative structure" in followup.text


def test_book_context_form_renders():
    response = client.get(f"/books/{book.id}/context")
    assert response.status_code == 200
    assert book.title in response.text


def test_book_context_update_persists_and_shows_saved():
    response = client.post(
        f"/books/{book.id}/context",
        data={
            "goal": "Understand distributed systems fundamentals",
            "prior_familiarity": "Some hands-on AI infra experience",
            "focus_areas": "Consensus and replication",
            "skip_areas": "Basic SQL",
        },
    )
    assert response.status_code == 200
    assert "Saved." in response.text
    assert "Understand distributed systems fundamentals" in response.text

    followup = client.get(f"/books/{book.id}/context")
    assert "Consensus and replication" in followup.text
    assert "Basic SQL" in followup.text


def test_book_context_not_found_returns_404():
    response = client.get("/books/9999/context")
    assert response.status_code == 404
