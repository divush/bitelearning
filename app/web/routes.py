"""Routes talk only to app.services.* - never app.models/app.db/app.generation/
app.progress/app.ingestion directly. That boundary is what makes the model-UI
separation real.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.services import book_service
from app.services.session import get_db
from app.web.templating import templates

router = APIRouter()


@router.get("/")
def index(request: Request, session=Depends(get_db)):
    books = book_service.list_books(session)
    if not books:
        return templates.TemplateResponse(
            request, "empty_library.html", {"books": [], "active_book_id": None}
        )
    return RedirectResponse(url=f"/books/{books[0].id}")


@router.get("/books/new")
def new_book_form(request: Request, session=Depends(get_db)):
    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request, "new_book.html", {"books": books, "active_book_id": None, "error": None}
    )


@router.post("/books")
async def create_book(
    request: Request,
    pdf: UploadFile = File(...),
    title: str = Form(""),
    session=Depends(get_db),
    books_dir=Depends(book_service.get_books_dir),
):
    if not (pdf.filename or "").lower().endswith(".pdf"):
        books = book_service.list_books(session)
        return templates.TemplateResponse(
            request,
            "new_book.html",
            {"books": books, "active_book_id": None, "error": "Please choose a PDF file."},
            status_code=400,
        )

    file_bytes = await pdf.read()
    try:
        book_id = book_service.add_book(
            session, file_bytes, pdf.filename, title=title.strip() or None, books_dir=books_dir
        )
    except Exception as e:
        books = book_service.list_books(session)
        return templates.TemplateResponse(
            request,
            "new_book.html",
            {"books": books, "active_book_id": None, "error": f"Couldn't add that book: {e}"},
            status_code=400,
        )

    return RedirectResponse(url=f"/books/{book_id}", status_code=303)


@router.get("/profile")
def profile_form(request: Request, session=Depends(get_db)):
    books = book_service.list_books(session)
    profile = book_service.get_learner_profile_view(session)
    return templates.TemplateResponse(
        request, "profile.html", {"books": books, "active_book_id": None, "profile": profile, "saved": False}
    )


@router.post("/profile")
def save_profile(
    request: Request,
    example_first_vs_theory_first: str = Form(""),
    session_length_pref: str = Form(""),
    depth_vs_breadth: str = Form(""),
    tone_pref: str = Form(""),
    raw_notes: str = Form(""),
    session=Depends(get_db),
):
    profile = book_service.update_learner_profile(
        session,
        example_first_vs_theory_first,
        session_length_pref,
        depth_vs_breadth,
        tone_pref,
        raw_notes,
    )
    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request, "profile.html", {"books": books, "active_book_id": None, "profile": profile, "saved": True}
    )


@router.get("/books/{book_id}")
def plan_view(request: Request, book_id: int, session=Depends(get_db)):
    try:
        workspace = book_service.get_book_workspace(session, book_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Book not found")

    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request,
        "plan.html",
        {"workspace": workspace, "books": books, "active_book_id": book_id},
    )


@router.get("/books/{book_id}/context")
def book_context_form(request: Request, book_id: int, session=Depends(get_db)):
    try:
        context = book_service.get_book_context_view(session, book_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Book not found")

    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request,
        "book_context.html",
        {"books": books, "active_book_id": book_id, "context": context, "saved": False},
    )


@router.post("/books/{book_id}/context")
def save_book_context(
    request: Request,
    book_id: int,
    goal: str = Form(""),
    prior_familiarity: str = Form(""),
    focus_areas: str = Form(""),
    skip_areas: str = Form(""),
    session=Depends(get_db),
):
    try:
        context = book_service.update_book_context(session, book_id, goal, prior_familiarity, focus_areas, skip_areas)
    except Exception:
        raise HTTPException(status_code=404, detail="Book not found")

    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request,
        "book_context.html",
        {"books": books, "active_book_id": book_id, "context": context, "saved": True},
    )


@router.get("/books/{book_id}/status")
def book_generation_status(request: Request, book_id: int, session=Depends(get_db)):
    workspace = book_service.get_book_workspace(session, book_id)
    return templates.TemplateResponse(request, "_generation_status.html", {"workspace": workspace})


@router.post("/books/{book_id}/plan")
def trigger_plan_generation(
    book_id: int, background_tasks: BackgroundTasks, force: bool = False
):
    background_tasks.add_task(book_service.start_plan_generation, book_id, force)
    return RedirectResponse(url=f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}/lessons/generate")
def trigger_lesson_generation(book_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(book_service.start_lesson_generation, book_id)
    return RedirectResponse(url=f"/books/{book_id}", status_code=303)


@router.get("/books/{book_id}/lessons/{order_index}")
def reader_view(request: Request, book_id: int, order_index: int, session=Depends(get_db)):
    try:
        lesson = book_service.get_lesson_detail(session, book_id, order_index)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lesson not found")

    books = book_service.list_books(session)
    return templates.TemplateResponse(
        request,
        "reader.html",
        {"lesson": lesson, "books": books, "active_book_id": book_id},
    )


@router.post("/books/{book_id}/lessons/{order_index}/complete")
def complete_lesson(request: Request, book_id: int, order_index: int, session=Depends(get_db)):
    lesson = book_service.mark_complete(session, book_id, order_index)
    return templates.TemplateResponse(request, "_complete_button.html", {"lesson": lesson})


@router.post("/books/{book_id}/lessons/{order_index}/incomplete")
def incomplete_lesson(request: Request, book_id: int, order_index: int, session=Depends(get_db)):
    lesson = book_service.mark_incomplete(session, book_id, order_index)
    return templates.TemplateResponse(request, "_complete_button.html", {"lesson": lesson})
