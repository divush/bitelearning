"""Shared prompt-formatting for LearnerProfile/BookContext, used by both
Plan Generation and Lesson Generation so the defaulting behavior stays identical.
"""

from app.models import BookContext, LearnerProfile

DEFAULT_PROFILE_TEXT = (
    "No profile set - assume moderate depth, mixed example/theory balance, ~20-30 min sessions."
)
DEFAULT_CONTEXT_TEXT = (
    "No specific context given - assume the learner wants broad coverage of the whole book "
    "at a generalist level."
)


def format_profile(profile: LearnerProfile | None) -> str:
    if profile is None:
        return DEFAULT_PROFILE_TEXT

    parts = []
    if profile.example_first_vs_theory_first:
        parts.append(f"Example-first vs theory-first: {profile.example_first_vs_theory_first}")
    if profile.session_length_pref:
        parts.append(f"Session length preference: {profile.session_length_pref}")
    if profile.depth_vs_breadth:
        parts.append(f"Depth vs breadth: {profile.depth_vs_breadth}")
    if profile.tone_pref:
        parts.append(f"Tone preference: {profile.tone_pref}")
    if profile.raw_notes:
        parts.append(f"Additional notes: {profile.raw_notes}")

    return "\n".join(parts) if parts else DEFAULT_PROFILE_TEXT


def format_context(context: BookContext | None) -> str:
    if context is None:
        return DEFAULT_CONTEXT_TEXT

    parts = []
    if context.goal:
        parts.append(f"Goal for this book: {context.goal}")
    if context.prior_familiarity:
        parts.append(f"Prior familiarity: {context.prior_familiarity}")
    if context.focus_areas:
        parts.append(f"Focus areas: {context.focus_areas}")
    if context.skip_areas:
        parts.append(f"Areas to skip: {context.skip_areas}")

    return "\n".join(parts) if parts else DEFAULT_CONTEXT_TEXT
