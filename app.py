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

import streamlit as st

from finance_bot import FinanceBot, subcat_browse_label
from llm_fallback import get_llm_fallback

st.set_page_config(page_title="FundGPT — Mutual Fund Bot", page_icon="📈", layout="wide")

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
    padding-bottom: 7.5rem;
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

/* Toolbar */
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
/* User's own messages: a filled, rounded "bubble" (rather than plain
   right-aligned text) so the user's input is visually set apart from
   the assistant's replies. Filled in the app's accent colour, with dark
   text for contrast against it. */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: var(--ff-accent) !important;
    text-align: left;
    color: #171717 !important;
    max-width: 80%;
    padding: 0.55rem 0.9rem !important;
    border-radius: 16px !important;
    display: inline-block;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] * {
    color: #171717 !important;
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

/* ---- Expander (Example queries) ---- */
[data-testid="stExpander"] {
    background: var(--ff-surface) !important;
    border: 1px solid var(--ff-border) !important;
    border-radius: var(--ff-radius) !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] p, [data-testid="stExpander"] li {
    color: var(--ff-text) !important;
}
[data-testid="stExpander"] code {
    background: var(--ff-surface-2) !important; color: var(--ff-accent) !important;
    border-radius: 6px; padding: 0.1rem 0.35rem;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading fund dataset...")
def load_bot() -> FinanceBot:
    # Always the fixed, static dataset bundled with the app -- there is no
    # way to point this at a different file or sheet at runtime.
    return FinanceBot()


def ask(prompt: str, llm_fallback) -> None:
    """Push a user prompt through the bot and append both turns to chat history."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    answer = bot.respond(prompt, llm_fallback=llm_fallback)
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
        '<div class="ff-title">FundGPT</div></div>'
        '<div class="ff-sub">Indian Mutual Fund analytics</div>',
        unsafe_allow_html=True,
    )

    try:
        bot = load_bot()
    except Exception as e:  # noqa: BLE001
        st.error(f"Failed to load dataset: {e}")
        st.stop()

    st.caption(f"{bot.fund_count():,} funds loaded")

    llm_fallback = get_llm_fallback()
    if llm_fallback:
        st.markdown('<div class="ff-pill on"><span class="dot"></span>General Q&A enabled</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ff-pill off"><span class="dot"></span>General Q&A off</div>', unsafe_allow_html=True)
        st.caption("Set GROQ_API_KEY to enable free-form finance questions.")

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
    '<div class="ff-title">Ask FundGPT</div></div>'
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
        ask(action, llm_fallback)

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
    ask(f"top 10 funds in {subcat_query}", llm_fallback)

# If a fund name link was just clicked in a table (e.g. "?fund=<name>"),
# treat it exactly like the user typing "tell me about <name>" and clear
# the query param so it doesn't refire on the next rerun.
if st.query_params.get("fund"):
    fund_query = st.query_params["fund"]
    st.query_params.clear()
    bot.pending = None
    ask(f"tell me about {fund_query}", llm_fallback)

# --- Toolbar: always-visible, works without ever opening the sidebar. ---
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

# --- Free-form input, always available at the bottom. ---
if prompt := st.chat_input("Ask about a fund or a category..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Looking that up..."):
            answer = bot.respond(prompt, llm_fallback=llm_fallback)
        st.markdown(answer, unsafe_allow_html=True)
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.messages.append({"role": "assistant", "content": answer})

with st.expander("Example queries"):
    st.markdown(
        "\n".join(
            [
                "- `top 10 funds in Large Cap Fund`",
                "- `best funds in ELSS`",
                "- `tell me about HDFC Flexi Cap fund`",
                "- `what does Sharpe ratio mean?`",
            ]
        )
    )
