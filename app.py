"""
app.py
------
Streamlit frontend for FundGPT — an AI-powered Mutual Fund analytics chatbot.

Responsive UI: a single, full-width nav list in the sidebar for desktop, plus
an equivalent tap-friendly flow inline in the chat itself (toolbar button +
suggestion chips + guided option buttons) so every feature is reachable on a
phone without ever needing to open the sidebar.

Run:
    streamlit run app.py
"""

import time

import streamlit as st

from finance_bot import FinanceBot, subcat_browse_label
from llm_fallback import get_llm_fallback, get_fund_risk_summarizer

st.set_page_config(page_title="Falakurra Fappu", page_icon="📈", layout="wide")

# ---------------------------------------------------------------------
# Style — minimal palette, generous tap targets, responsive grid.
# ---------------------------------------------------------------------
CUSTOM_CSS = """
<style>
/* Go fully dark end-to-end (previously we fought the environment's dark
   rendering with a light override, which is why the input box stayed
   dark while only some elements picked up the light theme — that
   mismatch is the "boxes / invisible text" bug). */
:root, html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    --text-color: #ECECEC !important;
    --background-color: #171717 !important;
    --secondary-background-color: #1E1E1E !important;
    --primary-color: #8B7CF6 !important;
    color-scheme: dark !important;
}
:root {
    --ff-bg: #171717;
    --ff-surface: #1E1E1E;
    --ff-surface-2: #262626;
    --ff-border: #2E2E2E;
    --ff-text: #ECECEC;
    --ff-text-muted: #9B9B9B;
    --ff-accent: #8B7CF6;
    --ff-radius: 10px;
}
html, body { color-scheme: dark !important; }

[data-testid="stAppViewContainer"] { background: var(--ff-bg) !important; }
[data-testid="stHeader"] { background: transparent !important; }

[data-testid="stAppViewContainer"] *, [data-testid="stSidebar"] * {
    color: var(--ff-text);
}

.main .block-container {
    max-width: 780px;
    padding-top: 1.4rem;
    padding-bottom: 11.5rem;
}

@media (max-width: 680px) {
    div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    div[data-testid="column"] { min-width: 100% !important; flex: 1 1 100% !important; }
    .main .block-container { padding-left: 0.9rem; padding-right: 0.9rem; }
}

/* ---- Brand header: plain, no emoji, no heavy effects ---- */
.ff-brand { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.1rem; }
.ff-brand .ff-mark {
    width: 32px; height: 32px; border-radius: 8px;
    background: var(--ff-surface-2); color: var(--ff-text) !important;
    border: 1px solid var(--ff-border);
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 0.85rem;
}
.ff-brand .ff-mark * { color: var(--ff-text) !important; }
.ff-brand .ff-title { font-size: 1.25rem; font-weight: 600; color: var(--ff-text) !important; }
.ff-sub { color: var(--ff-text-muted) !important; font-size: 0.88rem; margin: 0.15rem 0 1.2rem 0; }

/* ---- Status pill ---- */
.ff-pill {
    display: inline-flex; align-items: center; gap: 0.4rem;
    font-size: 0.78rem; font-weight: 500; border-radius: 999px;
    padding: 0.25rem 0.7rem; margin: 0.3rem 0 0.6rem 0;
    border: 1px solid var(--ff-border);
}
.ff-pill.on { color: var(--ff-accent) !important; }
.ff-pill.on * { color: var(--ff-accent) !important; }
.ff-pill.off { color: var(--ff-text-muted) !important; }
.ff-pill.off * { color: var(--ff-text-muted) !important; }
.ff-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background: var(--ff-surface) !important;
    border-right: 1px solid var(--ff-border);
}
[data-testid="stSidebar"] * { color: var(--ff-text) !important; }
.ff-nav-label {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--ff-text-muted) !important; margin: 1rem 0 0.4rem 0; font-weight: 600;
}
.ff-crumb {
    display: inline-flex; align-items: center; gap: 0.35rem;
    background: var(--ff-surface-2); color: var(--ff-text) !important;
    border: 1px solid var(--ff-border);
    border-radius: 999px; padding: 0.2rem 0.65rem;
    font-size: 0.78rem; font-weight: 500; margin: 0.2rem 0 0.5rem 0;
}
.ff-crumb * { color: var(--ff-text) !important; }

/* Plain, flat buttons — no gradients, no shadows */
div[data-testid="stButton"] button {
    width: 100%;
    text-align: left;
    border-radius: var(--ff-radius);
    border: 1px solid var(--ff-border);
    background: var(--ff-surface) !important;
    color: var(--ff-text) !important;
    padding: 0.5rem 0.85rem;
    font-size: 0.88rem;
    font-weight: 400;
    transition: border-color 0.12s ease, background 0.12s ease;
    box-shadow: none !important;
}
div[data-testid="stButton"] button * { color: inherit !important; }
div[data-testid="stButton"] button:hover {
    border-color: var(--ff-accent);
    background: var(--ff-surface-2) !important;
    color: var(--ff-text) !important;
    transform: none;
}
div[data-testid="stButton"] button[kind="primary"] {
    background: var(--ff-accent) !important;
    border-color: var(--ff-accent);
    color: #171717 !important;
}
div[data-testid="stButton"] button[kind="primary"] * { color: #171717 !important; }

/* Toolbar -- fixed directly above the chat-input bar so "Browse by
   category" / "Clear chat" read as attached to the search box rather
   than floating somewhere in the message thread. Same horizontal bounds
   as the chat column (min(780px, 94vw), centered) so its edges line up
   with the input box beneath it. */
.ff-toolbar {
    position: fixed;
    bottom: 5.7rem;
    left: 50%;
    transform: translateX(-50%);
    width: min(780px, 94vw);
    z-index: 999;
}
.ff-toolbar div[data-testid="stHorizontalBlock"] { gap: 0.6rem; }
.ff-toolbar div[data-testid="stButton"] button { font-weight: 500; }

/* Suggestion chips */
.ff-chip-row div[data-testid="stButton"] button {
    border-radius: 999px;
    text-align: center;
    font-size: 0.8rem;
    padding: 0.4rem 0.7rem;
}

/* Guided-flow option list */
.ff-option-row div[data-testid="stButton"] button { margin-bottom: 0.3rem; }
.ff-back div[data-testid="stButton"] button {
    width: auto; border: none; background: transparent !important;
    color: var(--ff-text-muted) !important; font-size: 0.8rem; padding: 0.2rem 0.3rem;
}
.ff-back div[data-testid="stButton"] button:hover { color: var(--ff-text) !important; background: transparent !important; }

/* ---- Chat messages: no card / bubble behind either side. Left/right
   alignment plus a small colour difference is the only distinction,
   the way a plain messaging thread reads. ---- */
[data-testid="stChatMessage"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0.5rem 0;
    gap: 0;
}
/* Hide the default avatar icons for a plain, minimal thread. */
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
    display: none !important;
}

[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    justify-content: flex-end;
}
/* User's own messages: a rounded bubble that hugs its content and sits
   flush right (Claude-style) -- NOT a full-width pill. Streamlit gives
   stChatMessageContent "flex: 1 1 auto" by default (so long assistant
   replies can wrap across the row), which is exactly why a short user
   message was stretching edge-to-edge -- "flex: none" stops it growing
   to fill the row, and width:fit-content + margin-left:auto then let it
   shrink to the text and hug the right edge. The bubble itself uses a
   muted neutral fill a shade lighter than the page background, with the
   normal light text colour, rather than a loud accent fill. */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    flex: none !important;
    background: var(--ff-surface-2) !important;
    color: var(--ff-text) !important;
    max-width: 80% !important;
    width: fit-content !important;
    margin-left: auto !important;
    padding: 0.6rem 1rem !important;
    border-radius: 18px !important;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] * {
    color: var(--ff-text) !important;
    text-align: left;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] p {
    margin: 0;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
    background: transparent !important;
    color: var(--ff-text-muted) !important;
    padding: 0; max-width: 100%;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] p,
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] li {
    color: var(--ff-text) !important;
}

/* Tables: horizontal scroll on small screens instead of squashing */
[data-testid="stChatMessageContent"] table {
    display: block; overflow-x: auto; white-space: nowrap;
    border-collapse: collapse; font-size: 0.86rem; max-width: 100%;
}
[data-testid="stChatMessageContent"] th {
    color: var(--ff-text-muted) !important; font-weight: 600;
    text-align: left;
}
[data-testid="stChatMessageContent"] th, [data-testid="stChatMessageContent"] td {
    padding: 0.4rem 0.65rem; border-bottom: 1px solid var(--ff-border);
}
[data-testid="stChatMessageContent"] a { color: var(--ff-accent) !important; font-weight: 500; text-decoration: underline; }

/* ---- Top-funds list: a stack of cards instead of a wide table, so a
   6-column comparison never forces horizontal scrolling or squashed text
   on a phone. Each card is full-width and its metric chips wrap onto as
   many lines as the screen needs. ---- */
.ff-fundlist { margin: 0.6rem 0 0.8rem 0; }
.ff-fundcard {
    background: var(--ff-surface);
    border: 1px solid var(--ff-border);
    border-radius: var(--ff-radius);
    padding: 0.75rem 0.9rem;
    margin-bottom: 0.6rem;
}
.ff-fundcard-head {
    display: flex; align-items: center; gap: 0.6rem;
    margin-bottom: 0.6rem;
}
.ff-rank {
    flex: none;
    width: 24px; height: 24px; border-radius: 50%;
    background: var(--ff-surface-2); border: 1px solid var(--ff-border);
    color: var(--ff-text-muted) !important;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.75rem; font-weight: 700;
}
.ff-fundcard:nth-child(1) .ff-rank,
.ff-fundcard:first-child .ff-rank { color: var(--ff-accent) !important; border-color: var(--ff-accent); }
.ff-fundname { flex: 1 1 auto; min-width: 0; }
.ff-fundname a {
    color: var(--ff-text) !important; font-weight: 600; font-size: 0.92rem;
    text-decoration: none !important; line-height: 1.3;
}
.ff-fundname a:hover { color: var(--ff-accent) !important; text-decoration: underline !important; }
.ff-metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
    gap: 0.5rem 0.4rem;
}
.ff-metric {
    display: flex; flex-direction: column; gap: 0.15rem;
    background: var(--ff-surface-2);
    border-radius: 8px;
    padding: 0.35rem 0.5rem;
}
.ff-metric-label {
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--ff-text-muted) !important; font-weight: 600;
}
.ff-metric-value { font-size: 0.86rem; font-weight: 600; color: var(--ff-text) !important; }
.ff-metric-value.pos { color: #4ADE80 !important; }
.ff-metric-value.neg { color: #F87171 !important; }

/* ---- Performance & Risk by Horizon: styled <details>/<summary> so it
   visibly reads as tappable (card + chevron + hover state) instead of
   relying on the browser's tiny, easy-to-miss default triangle. ---- */
.ff-hint { color: var(--ff-text-muted) !important; font-size: 0.8rem; font-style: italic; margin: 0.1rem 0 0.5rem 0; }
.ff-horizons { margin-bottom: 0.4rem; }
details.ff-horizon {
    background: var(--ff-surface);
    border: 1px solid var(--ff-border);
    border-radius: var(--ff-radius);
    margin-bottom: 0.45rem;
    overflow: hidden;
}
details.ff-horizon summary {
    list-style: none;
    cursor: pointer;
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.65rem 0.9rem;
    font-weight: 500;
    transition: background 0.12s ease;
}
details.ff-horizon summary::-webkit-details-marker { display: none; }
details.ff-horizon summary:hover { background: var(--ff-surface-2); }
details.ff-horizon summary::after {
    content: "";
    margin-left: auto;
    flex: none;
    width: 7px; height: 7px;
    border-right: 2px solid var(--ff-text-muted);
    border-bottom: 2px solid var(--ff-text-muted);
    transform: rotate(45deg);
    transition: transform 0.15s ease;
}
details.ff-horizon[open] summary::after { transform: rotate(-135deg); }
details.ff-horizon[open] summary { background: var(--ff-surface-2); border-bottom: 1px solid var(--ff-border); }
.ff-h-period {
    flex: none;
    background: var(--ff-surface-2);
    border: 1px solid var(--ff-border);
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
    font-size: 0.75rem; font-weight: 700;
    color: var(--ff-text) !important;
}
details.ff-horizon[open] .ff-h-period { background: var(--ff-accent) !important; color: #171717 !important; border-color: var(--ff-accent); }
.ff-h-return-wrap { display: flex; align-items: baseline; gap: 0.4rem; }
.ff-h-return-label { color: var(--ff-text-muted) !important; font-size: 0.78rem; }
.ff-h-return { font-weight: 700; color: var(--ff-text) !important; }
.ff-h-return.pos { color: #4ADE80 !important; }
.ff-h-return.neg { color: #F87171 !important; }
details.ff-horizon ul {
    margin: 0; padding: 0.7rem 1rem 0.85rem 2rem;
}
details.ff-horizon li { color: var(--ff-text) !important; padding: 0.15rem 0; }

/* ---- Fixed bottom chat-input bar ---- */
[data-testid="stBottomBlockContainer"], [data-testid="stBottom"] {
    background: linear-gradient(180deg, rgba(23,23,23,0), var(--ff-bg) 45%) !important;
}
[data-testid="stChatInput"] {
    background: var(--ff-surface) !important;
    border: 1px solid var(--ff-border) !important;
    border-radius: 999px !important;
    box-shadow: none !important;
}
[data-testid="stChatInput"] textarea,
div[data-baseweb="textarea"] textarea,
[data-testid="stChatInput"] input {
    color: #ECECEC !important;
    -webkit-text-fill-color: #ECECEC !important;
    caret-color: var(--ff-accent) !important;
    opacity: 1 !important;
    background: transparent !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #8A8A8A !important;
    -webkit-text-fill-color: #8A8A8A !important;
    opacity: 1 !important;
}
[data-testid="stChatInput"] button {
    background: var(--ff-accent) !important;
    border-radius: 999px !important;
}
[data-testid="stChatInput"] button svg { fill: #171717 !important; color: #171717 !important; }

/* ---- Loading splash overlay: full-viewport, shown at the top of every
   script run (see the unconditional st.empty() block below) and cleared
   right after load_bot() resolves -- so every browser refresh (and, as a
   side effect, every other rerun too, since Streamlit can't distinguish
   the two from pure Python) gets the same intentional loading moment
   instead of a half-drawn page. ---- */
.ff-loading-screen {
    position: fixed;
    inset: 0;
    z-index: 99999;
    background: var(--ff-bg);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
}
.ff-loading-gif {
    width: 220px;
    max-width: 60vw;
    border-radius: 12px;
    border: 1px solid var(--ff-border);
}
.ff-loading-text {
    color: var(--ff-text-muted) !important;
    font-size: 0.9rem;
    font-weight: 500;
    letter-spacing: 0.02em;
}

</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Direct-media Tenor link (the page URL redirects/embeds, so we point the
# <img> straight at the underlying .gif asset).
_LOADING_GIF_URL = "https://media1.tenor.com/m/Dpc_QB5RBW0AAAAC/uppi-kannada.gif"

# Shown at the top of every single script run -- NOT gated behind a
# "seen it once this session" flag. st.cache_resource already makes
# load_bot() fast after the very first process-wide load, so this splash
# is a brief, intentional beat on every refresh rather than a real wait.
# The cache-busting query param forces the browser to treat the <img> as
# a brand-new element each run, so the gif actually restarts playing from
# frame one instead of a stale frame just sitting there.
_loading_placeholder = st.empty()
_loading_placeholder.markdown(
    f'<div class="ff-loading-screen">'
    f'<img class="ff-loading-gif" src="{_LOADING_GIF_URL}?t={int(time.time() * 1000)}" alt="Loading" />'
    f'<div class="ff-loading-text">Loading fund data…</div>'
    f'</div>',
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Loading fund dataset...")
def load_bot() -> FinanceBot:
    # Always the fixed, static dataset bundled with the app -- there is no
    # way to point this at a different file or sheet at runtime.
    return FinanceBot()


def ask(prompt: str, llm_fallback, fund_summarizer=None) -> None:
    """Push a user prompt through the bot and append both turns to chat history."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    answer = bot.respond(prompt, llm_fallback=llm_fallback, fund_summarizer=fund_summarizer)
    st.session_state.messages.append({"role": "assistant", "content": answer})


def queue_action(action: str) -> None:
    """Queue a chat action to be resolved on the next run, before anything
    else renders — this is what lets a tap anywhere (sidebar, toolbar,
    chip, guided-flow button) show its result immediately."""
    st.session_state.pending_action = action
    st.rerun()


# ---------------------------------------------------------------------
# Sidebar — desktop-friendly single-column category browser
# ---------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        '<div class="ff-brand"><div class="ff-mark">FF</div>'
        '<div class="ff-title">Mee fund selection baga amateurish ga undhi</div></div>'
        '<div class="ff-sub">Nenu chebtha theesuko - MF analysis</div>',
        unsafe_allow_html=True,
    )

    try:
        bot = load_bot()
    except Exception as e:  # noqa: BLE001
        st.error(f"Failed to load dataset: {e}")
        st.stop()

    # Dataset (cached) is ready -- dismiss the splash for this run.
    _loading_placeholder.empty()

    st.caption(f"{bot.fund_count():,} funds loaded")

    llm_fallback = get_llm_fallback()
    if llm_fallback:
        st.markdown('<div class="ff-pill on"><span class="dot"></span>General Q&A enabled</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ff-pill off"><span class="dot"></span>General Q&A off</div>', unsafe_allow_html=True)
        st.caption("Set GROQ_API_KEY to enable free-form finance questions.")

    # Same GROQ_API_KEY config as llm_fallback above, but a separate,
    # narrowly-scoped call: given one fund's own metrics, it returns a
    # plain-language read of its risk/reward profile plus an explicit
    # "invest or not, and why" lean. Wired into every ask() call below so
    # it's attached to fund-profile answers wherever they're triggered
    # from (chat input, sidebar category buttons, chips, fund-name links).
    fund_summarizer = get_fund_risk_summarizer()
    if fund_summarizer:
        st.markdown('<div class="ff-pill on"><span class="dot"></span>AI fund summary enabled</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ff-pill off"><span class="dot"></span>AI fund summary off</div>', unsafe_allow_html=True)
        st.caption("Set GROQ_API_KEY to enable the AI invest/avoid summary on fund profiles.")

    if st.button("Clear chat", use_container_width=True):
        bot.pending = None
        st.session_state.messages = []
        st.session_state.selected_asset_type = None
        st.session_state.selected_subcat = None
        st.session_state.pending_action = None
        st.session_state.pending_back = False
        st.rerun()

    if "selected_asset_type" not in st.session_state:
        st.session_state.selected_asset_type = None
    if "selected_subcat" not in st.session_state:
        st.session_state.selected_subcat = None

    st.markdown('<div class="ff-nav-label">Browse by category</div>', unsafe_allow_html=True)

    if st.session_state.selected_asset_type is None:
        # --- Step 1: Asset Type ---
        for atype in bot.asset_types:
            if st.button(atype, key=f"asset_{atype}", use_container_width=True):
                st.session_state.selected_asset_type = atype
                st.session_state.selected_subcat = None
                st.rerun()
    else:
        # --- Step 2: Sub Category, with a breadcrumb back to step 1 ---
        atype = st.session_state.selected_asset_type
        crumb_cols = st.columns([4, 2])
        with crumb_cols[0]:
            st.markdown(f'<div class="ff-crumb">{atype}</div>', unsafe_allow_html=True)
        with crumb_cols[1]:
            if st.button("Change", key="asset_change", use_container_width=True):
                st.session_state.selected_asset_type = None
                st.rerun()

        # Labels shown here have both the "Close/Open Ended Schemes"
        # wrapper AND the redundant Asset-Type scheme prefix (e.g.
        # "Equity Scheme - ") stripped, since the Asset Type is already
        # implied by this list (see subcat_browse_label). The raw
        # dataset value is still what gets sent to the bot when clicked,
        # so matching stays exact.
        subcats = bot.asset_type_to_subcats.get(atype, [])
        for sc in subcats:
            if st.button(subcat_browse_label(sc), key=f"subcat_{sc}", use_container_width=True):
                st.session_state.selected_subcat = sc
                st.rerun()

# ---------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------
st.markdown(
    '<div class="ff-brand"><div class="ff-mark">FF</div>'
    '<div class="ff-title">Ask I say, Ask me </div></div>'
    '<div class="ff-sub">Top performing Mutual funds.</div>',
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
    "⚠️ **Disclaimer:**\n\n The fund rankings, scores, and analytics shown here are "
    "generated using our own research and calculations based primarily on approximately "
    "the last **3 years of historical NAV data** and other publicly available information. "
    "These results are **for informational and educational purposes only** and **do not "
    "constitute financial, investment, tax, or legal advice**. Past performance does not "
    "guarantee future returns. Please conduct your own research and consult a qualified "
    "financial advisor before making any investment decisions.\n\n"
    "**We are not responsible "
    "for any financial losses or investment decisions made based on this analysis.**"
            ),
        }
    ]
if "pending_action" not in st.session_state:
    st.session_state.pending_action = None
if "pending_back" not in st.session_state:
    st.session_state.pending_back = False

# --- Resolve any queued action first, before anything else renders. ---
if st.session_state.pending_action:
    action = st.session_state.pending_action
    st.session_state.pending_action = None
    if action == "__browse__":
        bot.pending = None
        st.session_state.messages.append({"role": "assistant", "content": bot.start_asset_type_flow()})
    else:
        ask(action, llm_fallback, fund_summarizer)

if st.session_state.pending_back:
    st.session_state.pending_back = False
    bot.pending = None
    st.session_state.messages.append({"role": "assistant", "content": bot.start_asset_type_flow()})

# If a Sub Category button was just clicked in the sidebar, resolve it
# (best-match against the fixed dataset) and inject the result as a chat turn.
if st.session_state.get("selected_subcat"):
    subcat_query = st.session_state.selected_subcat
    st.session_state.selected_subcat = None  # consume it so it only fires once
    bot.pending = None
    ask(f"top 10 funds in {subcat_query}", llm_fallback, fund_summarizer)

# If a fund name link was just clicked in a table (e.g. "?fund=<name>"),
# treat it exactly like the user typing "tell me about <name>" and clear
# the query param so it doesn't refire on the next rerun.
if st.query_params.get("fund"):
    fund_query = st.query_params["fund"]
    st.query_params.clear()
    bot.pending = None
    ask(f"tell me about {fund_query}", llm_fallback, fund_summarizer)

# --- Chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=True)

# --- Guided Asset Type -> Sub Category flow rendered as real tap targets,
#     right under the assistant's question, so it works identically on
#     phone and desktop without needing the sidebar. ---
payload = bot.pending_options_payload()
if payload:
    stage = bot.pending["stage"]
    if stage == "await_sub_category":
        st.markdown('<div class="ff-back">', unsafe_allow_html=True)
        if st.button("← Change asset type", key="ff_back"):
            st.session_state.pending_back = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="ff-option-row">', unsafe_allow_html=True)
    for opt in payload:
        if st.button(opt["label"], key=f"ff_opt_{stage}_{opt['index']}", use_container_width=True):
            queue_action(opt["value"])
    st.markdown('</div>', unsafe_allow_html=True)

# --- Quick-start suggestion chips, shown only at the start of a fresh chat. ---
elif len(st.session_state.messages) <= 1:
    st.markdown('<div class="ff-nav-label">Try asking</div>', unsafe_allow_html=True)
    st.markdown('<div class="ff-chip-row">', unsafe_allow_html=True)
    chip_queries = [
        "Top 10 funds in Large Cap Fund",
        "Best funds in ELSS",
        "Top 5 Corporate Bond funds",
        "Tell me about HDFC Flexi Cap Fund",
    ]
    chip_cols = st.columns(len(chip_queries))
    for col, q in zip(chip_cols, chip_queries):
        with col:
            if st.button(q, key=f"chip_{q}", use_container_width=True):
                queue_action(q)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Toolbar: pinned right above the input box so both are reachable
#     from the same spot, without ever needing to open the sidebar. ---
st.markdown('<div class="ff-toolbar">', unsafe_allow_html=True)
tb1, tb2 = st.columns(2)
with tb1:
    if st.button("Browse by category", use_container_width=True):
        queue_action("__browse__")
with tb2:
    if st.button("Clear chat", key="clear_main", use_container_width=True):
        bot.pending = None
        st.session_state.messages = []
        st.session_state.selected_asset_type = None
        st.session_state.selected_subcat = None
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- Free-form input, always available at the bottom. Routed through the
#     same queue_action() + rerun() pattern as every other entry point
#     (sidebar, toolbar, chips, guided-flow buttons) -- NOT rendered
#     inline here. Rendering inline would show the assistant's text
#     answer immediately, but any guided-flow buttons the answer implies
#     (e.g. "a few funds match X, which one?") are drawn by the payload
#     block ABOVE this one in the script, which would already have run
#     with the OLD pending state and so would show no buttons at all
#     until some unrelated rerun happened to catch up. ---
if prompt := st.chat_input("Ask about a fund or a category..."):
    # Every fresh search starts a brand-new thread rather than piling onto
    # the old one -- same reset the "Clear chat" button does -- so the
    # conversation always shows just the query just asked and its answer,
    # not a long scroll-back of unrelated earlier searches.
    bot.pending = None
    st.session_state.messages = []
    st.session_state.selected_asset_type = None
    st.session_state.selected_subcat = None
    queue_action(prompt)
