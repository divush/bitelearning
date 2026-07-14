"""Token-budgeted sub-chunking within a chapter. Splits on paragraph boundaries and
packs greedily up to a token budget, with a small token-level overlap carried into
the start of each subsequent chunk so context isn't lost at chunk boundaries.
"""

import re
from dataclasses import dataclass

import tiktoken

from app.config import CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS

_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class TextChunk:
    text: str
    token_count: int


def chunk_chapter_text(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[TextChunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    raw_chunks: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush_buffer():
        nonlocal buffer, buffer_tokens
        if buffer:
            raw_chunks.append("\n\n".join(buffer))
            buffer = []
            buffer_tokens = 0

    for para in paragraphs:
        para_token_ids = _ENCODING.encode(para)
        para_tokens = len(para_token_ids)

        if para_tokens > target_tokens:
            # a single paragraph bigger than the whole budget: flush, then hard-split it
            flush_buffer()
            for start in range(0, para_tokens, target_tokens):
                slice_ids = para_token_ids[start : start + target_tokens]
                raw_chunks.append(_ENCODING.decode(slice_ids))
            continue

        if buffer_tokens + para_tokens > target_tokens and buffer:
            flush_buffer()

        buffer.append(para)
        buffer_tokens += para_tokens

    flush_buffer()

    if overlap_tokens <= 0 or len(raw_chunks) <= 1:
        return [TextChunk(text=c, token_count=len(_ENCODING.encode(c))) for c in raw_chunks]

    overlapped: list[str] = [raw_chunks[0]]
    for i in range(1, len(raw_chunks)):
        prev_ids = _ENCODING.encode(raw_chunks[i - 1])
        tail_ids = prev_ids[-overlap_tokens:]
        tail_text = _ENCODING.decode(tail_ids)
        overlapped.append(tail_text + "\n\n" + raw_chunks[i])

    return [TextChunk(text=c, token_count=len(_ENCODING.encode(c))) for c in overlapped]
