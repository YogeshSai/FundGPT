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


# ----------------------------------------------------------------------
# Fund risk summary -- a separate, narrowly-scoped LLM call (different
# system prompt from the general Q&A fallback above) that takes a single
# fund's own return/risk metrics and produces a short plain-language
# summary plus an explicit lean ("worth considering" / "exercise
# caution" / "probably not"), so the reader gets an at-a-glance takeaway
# on the fund's profile page instead of having to read every metric
# themselves. Reuses the same GROQ_API_KEY config as get_llm_fallback().
# ----------------------------------------------------------------------
FUND_SUMMARY_SYSTEM_PROMPT = (
    "You are a cautious mutual fund risk analyst embedded in FundFinder. "
    "You will be given one fund's own return and risk metrics (returns "
    "across horizons, volatility, max drawdown, Sharpe/Sortino/Calmar "
    "ratios, Value at Risk, downside deviation, and its percentile rank "
    "vs. category peers). Using ONLY the numbers given:\n"
    "1. Write 3-5 short sentences in plain language on what the "
    "risk/reward profile looks like (return consistency, volatility, "
    "drawdown severity, and how it stacks up against peers).\n"
    "2. End with exactly one line starting with 'Lean:' followed by one "
    "of: 'Worth considering', 'Mixed / proceed with caution', or "
    "'Weak on these metrics' -- picked purely from the numbers, not "
    "general market views.\n"
    "3. Add a final short line reminding the reader this is an "
    "automated read of historical numbers only, is NOT personalized "
    "financial advice, and they should consult a qualified financial "
    "advisor and consider their own goals/horizon before investing.\n"
    "Do not repeat every number back -- reference only the few that "
    "matter most for the summary."
)


def get_fund_risk_summarizer():
    """Returns a callable `summarize(metrics_text: str) -> str` that
    turns a plain-text dump of one fund's metrics into a short AI
    summary + investment lean, or None if no GROQ_API_KEY is configured
    (or the `groq` package isn't installed) -- same fallback-to-None
    behavior as get_llm_fallback()."""
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        from groq import Groq
    except ImportError:
        return None

    client = Groq(api_key=api_key)

    def summarize(metrics_text: str) -> str:
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": FUND_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": metrics_text},
                ],
                temperature=0.3,
                max_tokens=350,
            )
            return resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            return f"_AI summary unavailable right now ({e})._"

    return summarize
