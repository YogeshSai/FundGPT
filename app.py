"""
app.py
------
Streamlit frontend for FundGPT — an AI-powered Mutual Fund analytics chatbot.

Responsive UI:
- Full-width navigation in the sidebar for desktop.
- Equivalent tap-friendly controls inside the chat for mobile.
- Loading GIF plays whenever the browser page/session is freshly loaded.
- GIF uses a unique cache-busting URL per browser session so the animation
  starts from frame 1 after a page refresh.

Run:
    streamlit run app.py
"""

import time
import streamlit as st

from finance_bot import FinanceBot, subcat_browse_label
from llm_fallback import get_llm_fallback, get_fund_risk_summarizer


# ---------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="Falakurra Fappu",
    page_icon="📈",
    layout="wide",
)


# ---------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------

CUSTOM_CSS = """
<style>

    /* -------------------------------------------------------------
       General page
    ------------------------------------------------------------- */

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    /* -------------------------------------------------------------
       Loading screen
    ------------------------------------------------------------- */

    .ff-loading {
        position: fixed;
        inset: 0;
        z-index: 999999;
        background: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
        text-align: center;
    }

    .ff-loading img {
        width: min(420px, 80vw);
        max-height: 420px;
        object-fit: contain;
        border-radius: 18px;
    }

    .ff-loading-text {
        margin-top: 18px;
        font-size: 18px;
        font-weight: 600;
        color: #333333;
    }

    /* -------------------------------------------------------------
       Sidebar
    ------------------------------------------------------------- */

    .ff-sidebar-title {
        font-size: 26px;
        font-weight: 800;
        margin-bottom: 5px;
    }

    .ff-sidebar-subtitle {
        font-size: 14px;
        color: #777777;
        line-height: 1.4;
        margin-bottom: 15px;
    }

    .ff-nav-label {
        font-size: 14px;
        font-weight: 700;
        margin-top: 12px;
        margin-bottom: 8px;
    }

    .ff-crumb {
        padding: 8px 12px;
        border-radius: 8px;
        background: rgba(128, 128, 128, 0.12);
        font-weight: 600;
        text-align: center;
    }

    /* -------------------------------------------------------------
       Status pills
    ------------------------------------------------------------- */

    .ff-pill {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        margin: 4px 0;
    }

    .ff-pill.on {
        background: rgba(46, 160, 67, 0.12);
        color: #238636;
    }

    .ff-pill.off {
        background: rgba(207, 34, 46, 0.10);
        color: #cf222e;
    }

    .ff-pill .dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: currentColor;
        display: inline-block;
    }

    /* -------------------------------------------------------------
       Main header
    ------------------------------------------------------------- */

    .ff-main-title {
        font-size: clamp(30px, 5vw, 48px);
        font-weight: 850;
        line-height: 1.05;
        margin-bottom: 5px;
    }

    .ff-main-subtitle {
        font-size: 17px;
        color: #777777;
        margin-bottom: 25px;
    }

    /* -------------------------------------------------------------
       Quick suggestion section
    ------------------------------------------------------------- */

    .ff-section-label {
        font-size: 13px;
        font-weight: 700;
        color: #777777;
        margin-top: 10px;
        margin-bottom: 8px;
    }

    .ff-option-row {
        margin-top: 10px;
        margin-bottom: 15px;
    }

    /* -------------------------------------------------------------
       Loading placeholder
    ------------------------------------------------------------- */

    .ff-loading-placeholder {
        min-height: 50vh;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* -------------------------------------------------------------
       Mobile
    ------------------------------------------------------------- */

    @media (max-width: 768px) {

        .block-container {
            padding-left: 0.8rem;
            padding-right: 0.8rem;
            padding-top: 1rem;
        }

        .ff-main-title {
            font-size: 32px;
        }

        .ff-main-subtitle {
            font-size: 15px;
        }

        /* Make Streamlit buttons comfortable on mobile */
        div.stButton > button {
            min-height: 46px;
            border-radius: 10px;
        }

        /* Prevent tiny quick-start columns */
        [data-testid="column"] {
            min-width: 0 !important;
        }

    }

</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Loading GIF
#
# IMPORTANT:
#
# We create the cache-busting token ONCE per Streamlit browser session.
#
# On:
#   - browser refresh -> new session -> new token -> GIF restarts
#   - st.rerun()      -> same session -> same token -> no GIF restart
#
# This avoids showing the GIF after every button click.
# ---------------------------------------------------------------------

_LOADING_GIF_BASE = (
    "https://media1.tenor.com/m/"
    "Dpc_QB5RBW0AAAAC/uppi-kannada.gif"
)


if "loading_gif_token" not in st.session_state:
    st.session_state.loading_gif_token = str(time.time_ns())


_loading_gif_url = (
    f"{_LOADING_GIF_BASE}"
    f"?v={st.session_state.loading_gif_token}"
)


# ---------------------------------------------------------------------
# Loading overlay
#
# This is displayed once for every fresh browser session.
# ---------------------------------------------------------------------

if "loading_screen_shown" not in st.session_state:

    loading_placeholder = st.empty()

    loading_placeholder.markdown(
        f"""
        <div class="ff-loading">
            <img
                src="{_loading_gif_url}"
                alt="Loading fund data..."
            />
            <div class="ff-loading-text">
                Loading fund data…
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

else:
    loading_placeholder = None


# ---------------------------------------------------------------------
# Load bot
# ---------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def load_bot() -> FinanceBot:
    """
    Load the fixed bundled FinanceBot dataset.

    cache_resource keeps the actual dataset/model loading fast after
    the first process-level load.
    """
    return FinanceBot()


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------

def ask(
    prompt: str,
    llm_fallback,
    fund_summarizer=None,
) -> None:
    """
    Push a user prompt through the bot and append both turns
    to chat history.
    """

    st.session_state.messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    answer = bot.respond(
        prompt,
        llm_fallback=llm_fallback,
        fund_summarizer=fund_summarizer,
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )


def queue_action(action: str) -> None:
    """
    Queue a chat action to be resolved on the next run.
    """

    st.session_state.pending_action = action
    st.rerun()


def reset_chat() -> None:
    """
    Reset the current chat and navigation state.
    """

    bot.pending = None

    st.session_state.messages = []
    st.session_state.selected_asset_type = None
    st.session_state.selected_subcat = None
    st.session_state.pending_action = None
    st.session_state.pending_back = False


# ---------------------------------------------------------------------
# Initialize session state
# ---------------------------------------------------------------------

if "selected_asset_type" not in st.session_state:
    st.session_state.selected_asset_type = None

if "selected_subcat" not in st.session_state:
    st.session_state.selected_subcat = None

if "pending_action" not in st.session_state:
    st.session_state.pending_action = None

if "pending_back" not in st.session_state:
    st.session_state.pending_back = False

if "messages" not in st.session_state:

    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "⚠️ **Disclaimer:**\n\n"
                "The fund rankings, scores, and analytics shown here are "
                "generated using our own research and calculations based "
                "primarily on approximately the last **3 years of historical "
                "NAV data** and other publicly available information.\n\n"
                "These results are **for informational and educational "
                "purposes only** and **do not constitute financial, "
                "investment, tax, or legal advice**.\n\n"
                "Past performance does not guarantee future returns. "
                "Please conduct your own research and consult a qualified "
                "financial advisor before making any investment decisions.\n\n"
                "**We are not responsible for any financial losses or "
                "investment decisions made based on this analysis.**"
            ),
        }
    ]


# ---------------------------------------------------------------------
# Load bot
# ---------------------------------------------------------------------

try:
    bot = load_bot()

except Exception as e:
    if loading_placeholder is not None:
        loading_placeholder.empty()

    st.error(f"Failed to load dataset: {e}")
    st.stop()


# ---------------------------------------------------------------------
# IMPORTANT:
#
# Remove loading overlay after the bot has loaded.
#
# Then mark the session as having shown the loading screen.
#
# Because this flag is stored in session_state:
#
#   Browser refresh:
#       session_state resets
#       -> loading GIF appears again
#
#   Normal st.rerun():
#       session_state survives
#       -> loading GIF does NOT appear again
# ---------------------------------------------------------------------

if loading_placeholder is not None:

    loading_placeholder.empty()

    st.session_state.loading_screen_shown = True


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------

with st.sidebar:

    st.markdown(
        """
        <div class="ff-sidebar-title">
            FF
        </div>

        <div class="ff-sidebar-subtitle">
            Mee fund selection baga amateurish ga undhi.<br>
            Nenu chebtha theesuko - MF analysis.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(f"{bot.fund_count():,} funds loaded")

    # -------------------------------------------------------------
    # General LLM fallback
    # -------------------------------------------------------------

    llm_fallback = get_llm_fallback()

    if llm_fallback:

        st.markdown(
            """
            <div class="ff-pill on">
                <span class="dot"></span>
                General Q&A enabled
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:

        st.markdown(
            """
            <div class="ff-pill off">
                <span class="dot"></span>
                General Q&A off
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            "Set GROQ_API_KEY to enable free-form finance questions."
        )

    # -------------------------------------------------------------
    # Fund risk summarizer
    # -------------------------------------------------------------

    fund_summarizer = get_fund_risk_summarizer()

    if fund_summarizer:

        st.markdown(
            """
            <div class="ff-pill on">
                <span class="dot"></span>
                AI fund summary enabled
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:

        st.markdown(
            """
            <div class="ff-pill off">
                <span class="dot"></span>
                AI fund summary off
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            "Set GROQ_API_KEY to enable the AI invest/avoid summary "
            "on fund profiles."
        )

    # -------------------------------------------------------------
    # Clear chat
    # -------------------------------------------------------------

    if st.button(
        "Clear chat",
        use_container_width=True,
        key="sidebar_clear_chat",
    ):

        reset_chat()
        st.rerun()

    # -------------------------------------------------------------
    # Category navigation
    # -------------------------------------------------------------

    st.markdown(
        '<div class="ff-nav-label">Browse by category</div>',
        unsafe_allow_html=True,
    )

    if st.session_state.selected_asset_type is None:

        # ---------------------------------------------------------
        # Step 1: Asset Type
        # ---------------------------------------------------------

        for atype in bot.asset_types:

            if st.button(
                atype,
                key=f"asset_{atype}",
                use_container_width=True,
            ):

                st.session_state.selected_asset_type = atype
                st.session_state.selected_subcat = None

                st.rerun()

    else:

        # ---------------------------------------------------------
        # Step 2: Sub Category
        # ---------------------------------------------------------

        atype = st.session_state.selected_asset_type

        crumb_cols = st.columns([4, 2])

        with crumb_cols[0]:

            st.markdown(
                f'<div class="ff-crumb">{atype}</div>',
                unsafe_allow_html=True,
            )

        with crumb_cols[1]:

            if st.button(
                "Change",
                key="asset_change",
                use_container_width=True,
            ):

                st.session_state.selected_asset_type = None
                st.session_state.selected_subcat = None

                st.rerun()

        subcats = bot.asset_type_to_subcats.get(
            atype,
            [],
        )

        for sc in subcats:

            if st.button(
                subcat_browse_label(sc),
                key=f"subcat_{sc}",
                use_container_width=True,
            ):

                st.session_state.selected_subcat = sc
                st.rerun()


# ---------------------------------------------------------------------
# Main header
# ---------------------------------------------------------------------

st.markdown(
    """
    <div class="ff-main-title">
        Ask I say, Ask me
    </div>

    <div class="ff-main-subtitle">
        Top performing Mutual funds.
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Resolve queued actions
# ---------------------------------------------------------------------

if st.session_state.pending_action:

    action = st.session_state.pending_action

    st.session_state.pending_action = None

    if action == "**browse**":

        bot.pending = None

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": bot.start_asset_type_flow(),
            }
        )

    else:

        ask(
            action,
            llm_fallback,
            fund_summarizer,
        )


# ---------------------------------------------------------------------
# Resolve pending back action
# ---------------------------------------------------------------------

if st.session_state.pending_back:

    st.session_state.pending_back = False

    bot.pending = None

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": bot.start_asset_type_flow(),
        }
    )


# ---------------------------------------------------------------------
# Sidebar subcategory click
# ---------------------------------------------------------------------

if st.session_state.get("selected_subcat"):

    subcat_query = st.session_state.selected_subcat

    # Consume it so it only fires once
    st.session_state.selected_subcat = None

    bot.pending = None

    ask(
        f"top 10 funds in {subcat_query}",
        llm_fallback,
        fund_summarizer,
    )


# ---------------------------------------------------------------------
# Fund name query parameter
# ---------------------------------------------------------------------

if st.query_params.get("fund"):

    fund_query = st.query_params["fund"]

    # Clear query parameter so it doesn't refire
    st.query_params.clear()

    bot.pending = None

    ask(
        f"tell me about {fund_query}",
        llm_fallback,
        fund_summarizer,
    )


# ---------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------

for msg in st.session_state.messages:

    with st.chat_message(msg["role"]):

        st.markdown(
            msg["content"],
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
# Guided flow
# ---------------------------------------------------------------------

payload = bot.pending_options_payload()

if payload:

    stage = bot.pending["stage"]

    # -------------------------------------------------------------
    # Subcategory stage
    # -------------------------------------------------------------

    if stage == "await_sub_category":

        st.markdown(
            '<div class="ff-option-row">',
            unsafe_allow_html=True,
        )

        if st.button(
            "← Change asset type",
            key="ff_back",
            use_container_width=True,
        ):

            st.session_state.pending_back = True
            st.rerun()

        st.markdown(
            "</div>",
            unsafe_allow_html=True,
        )

    # -------------------------------------------------------------
    # Options
    # -------------------------------------------------------------

    st.markdown(
        '<div class="ff-option-row">',
        unsafe_allow_html=True,
    )

    for opt in payload:

        if st.button(
            opt["label"],
            key=f"ff_opt_{stage}_{opt['index']}",
            use_container_width=True,
        ):

            queue_action(opt["value"])

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
# Quick-start suggestion chips
# ---------------------------------------------------------------------

elif len(st.session_state.messages) <= 1:

    st.markdown(
        '<div class="ff-section-label">Try asking</div>',
        unsafe_allow_html=True,
    )

    chip_queries = [
        "Top 10 funds in Large Cap Fund",
        "Best funds in ELSS",
        "Top 5 Corporate Bond funds",
        "Tell me about HDFC Flexi Cap Fund",
    ]

    chip_cols = st.columns(len(chip_queries))

    for col, q in zip(
        chip_cols,
        chip_queries,
    ):

        with col:

            if st.button(
                q,
                key=f"chip_{q}",
                use_container_width=True,
            ):

                queue_action(q)


# ---------------------------------------------------------------------
# Toolbar
# ---------------------------------------------------------------------

st.markdown(
    "<br>",
    unsafe_allow_html=True,
)

tb1, tb2 = st.columns(2)


with tb1:

    if st.button(
        "Browse by category",
        use_container_width=True,
        key="browse_toolbar",
    ):

        queue_action("**browse**")


with tb2:

    if st.button(
        "Clear chat",
        use_container_width=True,
        key="clear_main",
    ):

        reset_chat()
        st.rerun()


# ---------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------

if prompt := st.chat_input(
    "Ask about a fund or a category..."
):

    # Every fresh search starts a new thread
    bot.pending = None

    st.session_state.messages = []

    st.session_state.selected_asset_type = None
    st.session_state.selected_subcat = None

    queue_action(prompt)
