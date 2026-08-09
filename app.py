"""
app.py
------
Streamlit frontend for FundGPT — an AI-powered Mutual Fund analytics chatbot.

Responsive UI:
- Desktop-friendly category browser in the sidebar
- Mobile-friendly guided category flow inside the chat
- Chat input always available
- "Browse by category" and "Clear chat" buttons placed BELOW the chat input
- Quick-start suggestion chips
- Fund links through query parameters
- Optional LLM fallback for general finance questions

Run:
    streamlit run app.py
"""

import streamlit as st

from finance_bot import FinanceBot, subcat_browse_label
from llm_fallback import get_llm_fallback


# ---------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="FundGPT",
    page_icon="📈",
    layout="wide",
)


# ---------------------------------------------------------------------
# CUSTOM CSS
# ---------------------------------------------------------------------

CUSTOM_CSS = """
<style>

/* ================================================================
   GENERAL
   ================================================================ */

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}


/* ================================================================
   APP HEADER
   ================================================================ */

.ff-header {
    text-align: center;
    padding: 0.5rem 0 1rem 0;
}

.ff-header-title {
    font-size: 2.2rem;
    font-weight: 800;
    margin-bottom: 0.25rem;
}

.ff-header-subtitle {
    font-size: 1rem;
    opacity: 0.75;
}


/* ================================================================
   SIDEBAR
   ================================================================ */

.ff-sidebar-title {
    font-size: 1.5rem;
    font-weight: 800;
    margin-bottom: 0.2rem;
}

.ff-sidebar-subtitle {
    font-size: 0.9rem;
    opacity: 0.75;
    margin-bottom: 1rem;
}

.ff-nav-label {
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.65;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
}

.ff-crumb {
    padding: 0.55rem 0.75rem;
    border-radius: 0.5rem;
    background: rgba(128, 128, 128, 0.10);
    font-weight: 700;
    text-align: center;
}

.ff-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    font-size: 0.8rem;
    margin: 0.5rem 0;
}

.ff-pill .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}

.ff-pill.on {
    background: rgba(0, 180, 100, 0.10);
}

.ff-pill.on .dot {
    background: #00a86b;
}

.ff-pill.off {
    background: rgba(200, 100, 100, 0.10);
}

.ff-pill.off .dot {
    background: #d9534f;
}


/* ================================================================
   CHAT
   ================================================================ */

[data-testid="stChatMessage"] {
    border-radius: 12px;
}

[data-testid="stChatInput"] {
    margin-bottom: 0.5rem;
}


/* ================================================================
   BOTTOM ACTION BUTTONS
   ================================================================ */

.ff-bottom-actions {
    margin-top: 0.25rem;
    margin-bottom: 1rem;
}

.ff-bottom-actions button {
    min-height: 42px;
}


/* ================================================================
   OPTION BUTTONS
   ================================================================ */

.ff-option-row {
    margin-top: 0.5rem;
    margin-bottom: 1rem;
}


/* ================================================================
   MOBILE
   ================================================================ */

@media (max-width: 768px) {

    .block-container {
        padding-left: 0.8rem;
        padding-right: 0.8rem;
        padding-top: 0.8rem;
    }

    .ff-header-title {
        font-size: 1.7rem;
    }

    .ff-header-subtitle {
        font-size: 0.9rem;
    }

    .ff-bottom-actions button {
        min-height: 46px;
        font-size: 0.9rem;
    }

}

</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------
# LOAD BOT
# ---------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading fund dataset...")
def load_bot() -> FinanceBot:
    """
    Load the fixed/static fund dataset bundled with the application.
    """
    return FinanceBot()


try:
    bot = load_bot()

except Exception as e:
    st.error(f"Failed to load dataset: {e}")
    st.stop()


# ---------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# ---------------------------------------------------------------------

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


if "selected_asset_type" not in st.session_state:
    st.session_state.selected_asset_type = None


if "selected_subcat" not in st.session_state:
    st.session_state.selected_subcat = None


if "pending_action" not in st.session_state:
    st.session_state.pending_action = None


if "pending_back" not in st.session_state:
    st.session_state.pending_back = False


# ---------------------------------------------------------------------
# LLM FALLBACK
# ---------------------------------------------------------------------

llm_fallback = get_llm_fallback()


# ---------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------

def ask(prompt: str, llm_fallback) -> None:
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
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )


def queue_action(action: str) -> None:
    """
    Queue a chat action to be resolved on the next Streamlit run.

    This allows sidebar buttons, toolbar buttons, chips and guided
    buttons to behave consistently.
    """

    st.session_state.pending_action = action
    st.rerun()


def clear_chat() -> None:
    """
    Reset the conversation and all category selections.
    """

    bot.pending = None

    st.session_state.messages = []

    st.session_state.selected_asset_type = None
    st.session_state.selected_subcat = None

    st.session_state.pending_action = None
    st.session_state.pending_back = False

    st.rerun()


# ---------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------

with st.sidebar:

    st.markdown(
        """
        <div class="ff-sidebar-title">
            📈 FundGPT
        </div>

        <div class="ff-sidebar-subtitle">
            Mee fund selection baga amateurish ga undhi.<br>
            Nanu adugu — nenu chebtha.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        f"{bot.fund_count():,} funds loaded"
    )

    # LLM status
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

    # Sidebar clear button
    if st.button(
        "Clear chat",
        key="clear_sidebar",
        use_container_width=True,
    ):
        clear_chat()

    st.markdown(
        '<div class="ff-nav-label">Browse by category</div>',
        unsafe_allow_html=True,
    )

    # ---------------------------------------------------------------
    # STEP 1 — ASSET TYPE
    # ---------------------------------------------------------------

    if st.session_state.selected_asset_type is None:

        for atype in bot.asset_types:

            if st.button(
                atype,
                key=f"asset_{atype}",
                use_container_width=True,
            ):

                st.session_state.selected_asset_type = atype
                st.session_state.selected_subcat = None

                st.rerun()

    # ---------------------------------------------------------------
    # STEP 2 — SUB CATEGORY
    # ---------------------------------------------------------------

    else:

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
# MAIN HEADER
# ---------------------------------------------------------------------

st.markdown(
    """
    <div class="ff-header">

        <div class="ff-header-title">
            📈 FundGPT
        </div>

        <div class="ff-header-subtitle">
            Ask me anything about Mutual Funds
        </div>

    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# RESOLVE QUEUED ACTION
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
        )


# ---------------------------------------------------------------------
# HANDLE BACK ACTION
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
# HANDLE SIDEBAR SUB CATEGORY SELECTION
# ---------------------------------------------------------------------

if st.session_state.get("selected_subcat"):

    subcat_query = st.session_state.selected_subcat

    # Consume selection
    st.session_state.selected_subcat = None

    bot.pending = None

    ask(
        f"top 10 funds in {subcat_query}",
        llm_fallback,
    )


# ---------------------------------------------------------------------
# HANDLE FUND LINK QUERY PARAMETER
# ---------------------------------------------------------------------

if st.query_params.get("fund"):

    fund_query = st.query_params["fund"]

    # Prevent the same query from firing again
    st.query_params.clear()

    bot.pending = None

    ask(
        f"tell me about {fund_query}",
        llm_fallback,
    )


# ---------------------------------------------------------------------
# CHAT HISTORY
# ---------------------------------------------------------------------

for msg in st.session_state.messages:

    with st.chat_message(msg["role"]):

        st.markdown(
            msg["content"],
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
# GUIDED ASSET TYPE → SUB CATEGORY FLOW
# ---------------------------------------------------------------------

payload = bot.pending_options_payload()


if payload:

    stage = bot.pending["stage"]

    # ---------------------------------------------------------------
    # SUB CATEGORY SCREEN
    # ---------------------------------------------------------------

    if stage == "await_sub_category":

        st.markdown(
            "",
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
            "",
            unsafe_allow_html=True,
        )

    # ---------------------------------------------------------------
    # OPTION BUTTONS
    # ---------------------------------------------------------------

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

            queue_action(
                opt["value"]
            )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
# QUICK START SUGGESTIONS
# ---------------------------------------------------------------------

elif len(st.session_state.messages) <= 1:

    st.markdown(
        "### Try asking",
    )

    chip_queries = [
        "Top 10 funds in Large Cap Fund",
        "Best funds in ELSS",
        "Top 5 Corporate Bond funds",
        "Tell me about HDFC Flexi Cap Fund",
    ]

    chip_cols = st.columns(
        len(chip_queries)
    )

    for col, query in zip(
        chip_cols,
        chip_queries,
    ):

        with col:

            if st.button(
                query,
                key=f"chip_{query}",
                use_container_width=True,
            ):

                queue_action(query)


# ---------------------------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------------------------

if prompt := st.chat_input(
    "Ask about a fund or a category..."
):

    queue_action(prompt)


# ---------------------------------------------------------------------
# BOTTOM ACTION BAR
# ---------------------------------------------------------------------
#
# IMPORTANT:
# These buttons intentionally appear AFTER st.chat_input().
# Therefore they are visually positioned below the text box.
# ---------------------------------------------------------------------

st.markdown(
    '<div class="ff-bottom-actions">',
    unsafe_allow_html=True,
)

bottom_col1, bottom_col2 = st.columns(2)


with bottom_col1:

    if st.button(
        "📂 Browse by category",
        key="browse_bottom",
        use_container_width=True,
    ):

        queue_action("**browse**")


with bottom_col2:

    if st.button(
        "🗑️ Clear chat",
        key="clear_bottom",
        use_container_width=True,
    ):

        clear_chat()


st.markdown(
    "</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# EXAMPLE QUERIES
# ---------------------------------------------------------------------

with st.expander(
    "💡 Example queries"
):

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
