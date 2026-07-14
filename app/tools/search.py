"""Search tool used by Lesson Generation's research step. Kept behind a stable,
provider-agnostic interface (`web_search`) so the underlying search provider can
be swapped later without touching any other module - only this file's internals
would need to change.
"""

import json
from typing import TypedDict

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_core.tools import tool

NUM_RESULTS = 5


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str


def _duckduckgo_search(query: str) -> list[SearchResult]:
    raw_tool = DuckDuckGoSearchResults(output_format="list", num_results=NUM_RESULTS)
    raw_results = raw_tool.invoke(query)
    return [
        SearchResult(title=r.get("title", ""), url=r.get("link", ""), snippet=r.get("snippet", ""))
        for r in raw_results
    ]


@tool
def web_search(query: str) -> str:
    """Search the web and return relevant results (title, url, snippet) for the given query.
    Use this to find real-world case studies, canonical papers/tools, or notable production
    incidents that would meaningfully enrich a lesson - not to look up facts already covered
    in the book's own text.
    """
    return json.dumps(_duckduckgo_search(query), indent=2)
