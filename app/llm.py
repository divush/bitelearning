"""Thin factory for chat models, so every generation module pulls from one place."""

from langchain_openai import ChatOpenAI

from app.config import OPENAI_API_KEY


def get_chat_model(model: str, temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(model=model, temperature=temperature, api_key=OPENAI_API_KEY)
