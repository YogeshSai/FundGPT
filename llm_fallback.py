"""
llm_fallback.py
----------------
Optional LLM fallback for free-form finance questions that aren't a
direct "top N funds" or "tell me about <fund>" request (e.g. "what does
Sharpe ratio mean?").

Uses the Groq API (fast inference, generous free tier) when a
GROQ_API_KEY is configured -- either as an environment variable or as
a Streamlit secret. If no key is configured, get_llm_fallback() returns
None and the app falls back to the guided Asset Type / Sub Category
button flow instead of free-form Q&A (see the "General Q&A off" pill
in the sidebar).
"""

from __future__ import annotations

import os

SYSTEM_PROMPT = (
    "You are a helpful assistant embedded in FundFinder, a mutual fund "
    "analytics chatbot. Answer general finance / mutual fund questions "
    "concisely and in plain language. You do NOT have access to the "
    "live fund dataset in this fallback -- for fund-specific rankings "
    "or metrics, tell the user to ask something like 'top 10 large cap "
    "funds' or 'tell me about <fund name>' instead, which are handled "
    "directly by the app. Never give personalized investment advice; "
    "include a brief reminder to consult a qualified financial advisor "
    "before making investment decisions."
)

MODEL = "llama-3.3-70b-versatile"


def _get_api_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("GROQ_API_KEY")
    except Exception:
        return None


def get_llm_fallback():
    """Returns a callable `fallback(query: str) -> str`, or None if no
    GROQ_API_KEY is configured (or the `groq` package isn't installed)."""
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        from groq import Groq
    except ImportError:
        return None

    client = Groq(api_key=api_key)

    def fallback(query: str) -> str:
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0.4,
                max_tokens=500,
            )
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            return f"Sorry, I couldn't reach the general Q&A model right now ({e})."

    return fallback
