import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.generation.lesson_generator import (
    Exercise,
    ExternalReference,
    LessonContent,
    build_context_messages,
    build_lesson_graph,
    generate_book_lessons,
    generate_lesson,
)
from app.models import Base, Book, Chapter, Chunk, Lesson, Plan


@tool
def fake_search_tool(query: str) -> str:
    """Fake search tool for tests - no network."""
    return json.dumps([{"title": "Fake Result", "url": "https://example.com/x", "snippet": "info"}])


class _StubToolCallingModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


class _StubComposeModel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.result


class _SequentialGraph:
    """Stands in for a compiled LangGraph graph: returns one canned final_content per call."""

    def __init__(self, results):
        self.results = list(results)
        self.invocations = 0

    def invoke(self, state, config=None):
        self.invocations += 1
        return {"final_content": self.results.pop(0)}


class _AssertGeneratingGraph:
    """Confirms exactly one Lesson is visible with status='generating' at the
    moment the (slow) generation call would happen - proves the ordering without
    needing real concurrency."""

    def __init__(self, results, session, book_id):
        self.results = list(results)
        self.session = session
        self.book_id = book_id

    def invoke(self, state, config=None):
        generating = self.session.query(Lesson).filter_by(book_id=self.book_id, status="generating").all()
        assert len(generating) == 1
        return {"final_content": self.results.pop(0)}


def test_build_context_messages_includes_all_sections():
    lesson = Lesson(title="Test Lesson", topic_summary="Covers X and Y.")

    messages = build_context_messages(
        lesson,
        source_chunks_text="SOURCE_TEXT_MARKER",
        chapter_summaries_text="CHAPTER_SUMMARIES_MARKER",
        prior_lesson_summaries_text="PRIOR_LESSON_MARKER",
        profile=None,
        context=None,
    )

    assert len(messages) == 2
    human_content = messages[1].content
    assert "Test Lesson" in human_content
    assert "Covers X and Y." in human_content
    assert "SOURCE_TEXT_MARKER" in human_content
    assert "CHAPTER_SUMMARIES_MARKER" in human_content
    assert "PRIOR_LESSON_MARKER" in human_content


def test_lesson_graph_searches_once_then_composes():
    tool_call_message = AIMessage(
        content="",
        tool_calls=[{"name": "fake_search_tool", "args": {"query": "raft consensus"}, "id": "call_1"}],
    )
    final_research_message = AIMessage(content="I have enough information now.")
    stub_research = _StubToolCallingModel([tool_call_message, final_research_message])

    final_lesson = LessonContent(core_content="The final lesson body.", references=[], exercises=[])
    stub_compose = _StubComposeModel(final_lesson)

    graph = build_lesson_graph(stub_research, stub_compose, fake_search_tool)

    lesson = Lesson(title="Consensus", topic_summary="Covers consensus algorithms.")
    result = generate_lesson(lesson, "source text", "chapter summaries", "(none)", None, None, graph=graph)

    assert result == final_lesson
    assert len(stub_research.calls) == 2
    assert len(stub_compose.calls) == 1


def _make_test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_book_with_plan(session, num_lessons=2):
    book = Book(title="Test Book", source_filename="test.pdf", num_pages=50, status="parsed")
    session.add(book)
    session.flush()

    chapters = []
    for i in range(num_lessons):
        chapter = Chapter(
            book_id=book.id,
            order_index=i,
            title=f"Chapter {i + 1}",
            start_page=i * 10,
            end_page=i * 10 + 9,
            summary=f"Summary of chapter {i + 1}",
        )
        session.add(chapter)
        session.flush()
        session.add(Chunk(chapter_id=chapter.id, order_index=0, token_count=50, text=f"Chunk text {i + 1}"))
        chapters.append(chapter)
    session.commit()

    plan = Plan(book_id=book.id, status="complete")
    session.add(plan)
    session.flush()

    lessons = []
    for i, chapter in enumerate(chapters):
        lesson = Lesson(
            plan_id=plan.id,
            book_id=book.id,
            order_index=i,
            title=f"Lesson {i + 1}",
            topic_summary=f"Covers chapter {i + 1}",
            source_chapter_ids=json.dumps([chapter.id]),
            status="planned",
        )
        session.add(lesson)
        lessons.append(lesson)
    session.commit()

    return book, plan, lessons


def test_generate_book_lessons_persists_and_is_resumable():
    session = _make_test_session()
    book, plan, lessons = _seed_book_with_plan(session, num_lessons=2)

    stub_results = [
        LessonContent(
            core_content="Content A",
            references=[ExternalReference(title="R", url="http://x", why_relevant="y")],
            exercises=[],
        ),
        LessonContent(core_content="Content B", references=[], exercises=[Exercise(prompt="Do X")]),
    ]
    graph = _SequentialGraph(stub_results)

    results = list(generate_book_lessons(book.id, graph=graph, session=session))
    statuses = {r.lesson.title: r.status for r in results}
    assert statuses == {"Lesson 1": "generated", "Lesson 2": "generated"}

    assert lessons[0].content == "Content A"
    assert json.loads(lessons[0].external_references)[0]["title"] == "R"
    assert lessons[0].status == "generated"
    assert lessons[1].content == "Content B"
    assert json.loads(lessons[1].exercises)[0]["prompt"] == "Do X"

    # resumability: rerun without force -> both skipped, no new graph invocations
    graph2 = _SequentialGraph([])
    results2 = list(generate_book_lessons(book.id, graph=graph2, session=session))
    statuses2 = {r.lesson.title: r.status for r in results2}
    assert statuses2 == {"Lesson 1": "skipped_existing", "Lesson 2": "skipped_existing"}
    assert graph2.invocations == 0


def test_generate_book_lessons_marks_failure_and_continues():
    session = _make_test_session()
    book, plan, lessons = _seed_book_with_plan(session, num_lessons=2)

    class _FailThenSucceedGraph:
        def __init__(self):
            self.calls = 0

        def invoke(self, state, config=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("search API down")
            return {"final_content": LessonContent(core_content="Content B", references=[], exercises=[])}

    results = list(generate_book_lessons(book.id, graph=_FailThenSucceedGraph(), session=session))
    statuses = {r.lesson.title: r.status for r in results}
    assert statuses == {"Lesson 1": "failed", "Lesson 2": "generated"}
    assert results[0].error == "search API down"

    assert lessons[0].status == "failed"
    assert lessons[1].status == "generated"
    assert lessons[1].content == "Content B"


def test_generate_book_lessons_lesson_index_filters_to_one_lesson():
    session = _make_test_session()
    book, plan, lessons = _seed_book_with_plan(session, num_lessons=3)

    graph = _SequentialGraph([LessonContent(core_content="Only B", references=[], exercises=[])])

    results = list(generate_book_lessons(book.id, lesson_index=1, graph=graph, session=session))

    assert [r.lesson.title for r in results] == ["Lesson 2"]
    assert lessons[1].content == "Only B"
    assert lessons[0].status == "planned"
    assert lessons[2].status == "planned"


def test_generate_book_lessons_sets_generating_status_before_each_lesson():
    session = _make_test_session()
    book, plan, lessons = _seed_book_with_plan(session, num_lessons=2)

    graph = _AssertGeneratingGraph(
        [
            LessonContent(core_content="Content A", references=[], exercises=[]),
            LessonContent(core_content="Content B", references=[], exercises=[]),
        ],
        session,
        book.id,
    )

    results = list(generate_book_lessons(book.id, graph=graph, session=session))

    assert [r.status for r in results] == ["generated", "generated"]
    assert lessons[0].status == "generated"
    assert lessons[1].status == "generated"
