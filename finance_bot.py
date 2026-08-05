"""
finance_bot.py
--------------
Core logic for FundFinder: an AI-powered mutual fund analytics chatbot.

Responsibilities:
  1. Load & validate the fund dataset from the fixed local file
     "MF_Risk_Metrics_1.xlsx" (sheet "Risk Metrics"), located in the same
     folder as this script. This is the ONLY data source the bot will ever
     read from -- there is no upload path, and the loader does not accept
     an alternate file or sheet name.
  2. Answer "top performing funds in <Sub Category>" queries, matching the
     user's category text against the dataset's real Sub Category values by
     highest similarity score (no need to type it exactly).
  3. Answer "tell me about <Scheme Name>" queries with the full metric sheet.
  4. Lightweight intent detection (regex/keyword based -- no LLM required
     for the two core features above).
  5. A guided "Asset Type -> Sub Category" button flow: when the bot can't
     confidently match a category from free text (or the user just wants to
     browse), it first offers Asset Type options, then -- once picked --
     offers the Sub Categories that belong to that Asset Type, and finally
     shows the top funds for whichever Sub Category best matches the pick.
     Sub Category options are always shown to the user with clean, friendly
     labels (see `clean_subcat_label`) and as a single markdown table rather
     than a bracketed list. `pending_options_payload()` exposes the same
     options as structured data so a front end can render real clickable
     buttons / a side-panel list instead of (or in addition to) the table.
  6. Optional LLM fallback (Groq) for free-form finance questions that
     aren't a direct top-N or fund-lookup request. See llm_fallback.py.
"""

from __future__ import annotations

import difflib
import html
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import pandas as pd

# ----------------------------------------------------------------------
# Fixed dataset location -- this is the single, static source of data.
# There is intentionally no way to point the bot at a different file,
# a different sheet, or an uploaded workbook.
# ----------------------------------------------------------------------

DATA_FILENAME = "MF_Risk_Metrics_1.xlsx"
SHEET_NAME = "Risk Metrics"

# Backward-compatible aliases (older app.py versions import these names).
# The dataset itself is still fixed/static either way -- these are just
# read-only names pointing at the same constants above.
DEFAULT_DATA_FILENAME = DATA_FILENAME
DEFAULT_SHEET_NAME = SHEET_NAME


def _data_path() -> str:
    """Resolve MF_Risk_Metrics_1.xlsx sitting next to this script."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, DATA_FILENAME)


# ----------------------------------------------------------------------
# Column groupings used for pretty-printing a fund's full profile
# ----------------------------------------------------------------------

BASIC_COLS = [
    "Scheme Code", "Scheme Name", "AMC (Fund House)", "Sub Category",
    "Asset Class", "ELSS", "Latest NAV Date", "Latest NAV",
]
COST_COLS = ["TER (%)", "TER_Regular (%)", "TER_Direct (%)"]

HORIZONS = ["6M", "1Y", "3Y", "5Y"]
METRIC_SUFFIXES = [
    "CAGR", "Volatility", "MaxDrawdown", "Sharpe", "Sortino",
    "DownsideDev", "VaR95", "Calmar", "RollMean", "RollMin", "RollMax",
]
PEER_PCTILE_COLS = [
    "3Y_CAGR_PeerPctile", "3Y_Sharpe_PeerPctile", "3Y_Sortino_PeerPctile",
    "3Y_Calmar_PeerPctile", "3Y_MaxDrawdown_PeerPctile", "3Y_Volatility_PeerPctile",
    "3Y_VaR95_PeerPctile", "3Y_DownsideDev_PeerPctile",
]
SCORE_COLS = ["Composite_Score", "Peer_Rank"]

TOP_N_TABLE_COLS = [
    "Scheme Name", "1Y_CAGR", "3Y_CAGR", "5Y_CAGR", "Peer_Rank",
]

# Columns shown in the chat's Top-N table. AMC, 3Y Sharpe, TER, and
# Composite Score are deliberately left out here -- they're already shown
# when the user opens a specific fund's full profile, so repeating them in
# the summary table is redundant.
TOP_N_DISPLAY_COLS = ["Scheme Name", "1Y_CAGR", "3Y_CAGR", "5Y_CAGR", "Peer_Rank"]

# Underscore-free display headers for the Top-N table.
TOP_N_COL_LABELS = {
    "Scheme Name": "Scheme Name",
    "1Y_CAGR": "1Y CAGR",
    "3Y_CAGR": "3Y CAGR",
    "5Y_CAGR": "5Y CAGR",
    "Peer_Rank": "Peer Rank",
}

# These columns are stored as fractions (0.04 == 4%) and are rendered with
# a trailing '%' in the Top-N table.
PERCENT_COLS = {"1Y_CAGR", "3Y_CAGR", "5Y_CAGR"}

FRIENDLY_LABELS = {
    "CAGR": "CAGR (Annualised Return)",
    "Volatility": "Volatility (Std. Dev.)",
    "MaxDrawdown": "Max Drawdown",
    "Sharpe": "Sharpe Ratio",
    "Sortino": "Sortino Ratio",
    "DownsideDev": "Downside Deviation",
    "VaR95": "Value at Risk (95%)",
    "Calmar": "Calmar Ratio",
    "RollMean": "Rolling Return (Mean)",
    "RollMin": "Rolling Return (Min)",
    "RollMax": "Rolling Return (Max)",
    
}

# Minimum similarity score (0-1) required to auto-accept a free-text
# Sub Category match without falling back to the guided button flow.
SUBCAT_MATCH_THRESHOLD = 0.35

# ----------------------------------------------------------------------
# De-duplicating "same fund, different plan/option" rows
# ----------------------------------------------------------------------
# The dataset often has one row per (Scheme, Plan, Option) combination --
# e.g. "WhiteOak Capital Large Cap Fund Direct Plan Growth" and
# "WhiteOak Capital Large Cap Fund Direct Plan IDCW" are the *same*
# underlying fund/portfolio, just different payout options, and end up
# with identical (or near-identical) return/risk metrics. We collapse
# these down to a single row -- preferring the Growth variant -- before
# ranking/displaying "top funds".
_OPTION_KEYWORDS = ["idcw", "dividend", "growth", "payout", "reinvestment", "bonus"]


def _fund_dedup_key(name: str) -> str:
    """Normalized identity for a fund, with the plan-option word (Growth /
    IDCW / Dividend / ...) stripped out so different options of the same
    underlying fund collapse to the same key. 'Direct'/'Regular Plan' is
    deliberately kept, since those ARE genuinely different funds/TERs."""
    text = str(name).lower()
    for kw in _OPTION_KEYWORDS:
        text = re.sub(rf"\b{kw}\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text


def _is_growth_variant(name: str) -> bool:
    return "growth" in str(name).lower()


def dedup_funds(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse rows that represent the same underlying fund under
    different plan-options (Growth/IDCW/Dividend/...) down to one row
    each, keeping the Growth variant when one is present."""
    if df.empty or "Scheme Name" not in df.columns:
        return df
    work = df.copy()
    work["_dedup_key"] = work["Scheme Name"].apply(_fund_dedup_key)
    work["_is_growth"] = work["Scheme Name"].apply(_is_growth_variant)
    # Growth rows sort first, so drop_duplicates(keep="first") keeps them.
    work = work.sort_values("_is_growth", ascending=False, kind="stable")
    work = work.drop_duplicates(subset="_dedup_key", keep="first")
    return work.drop(columns=["_dedup_key", "_is_growth"])


# ----------------------------------------------------------------------
# Sub Category label cleanup
# ----------------------------------------------------------------------
# Raw dataset values look like "Open Ended Schemes(Debt Scheme - Banking
# and PSU Fund)" or "Close Ended Schemes(ELSS)". Matching still runs
# against the raw values (they're what's actually in the dataset), but
# anything shown to the user -- in chat text, tables, or button/side-panel
# labels -- goes through this cleaner first.
_WRAPPER_PHRASES = ["close ended schemes", "open ended schemes"]


def clean_subcat_label(raw: str) -> str:
    """Human-friendly Sub Category label with the 'Close/Open Ended
    Schemes' wrapper text and surrounding parentheses stripped out.

    'Open Ended Schemes(Debt Scheme - Banking and PSU Fund)' ->
    'Debt Scheme - Banking and PSU Fund'
    'Close Ended Schemes(ELSS)' -> 'ELSS'
    """
    if not raw:
        return raw
    text = str(raw)
    for phrase in _WRAPPER_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    text = text.replace("(", "").replace(")", "")
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text or str(raw)


def _fund_link(name: str) -> str:
    """Raw HTML anchor (not markdown syntax) so we can force target="_self" --
    plain markdown '[text](url)' links get target="_blank" forced on them by
    Streamlit's renderer, which would open a new tab instead of resolving in
    the same chat."""
    safe_name = html.escape(str(name))
    return f'<a href="?fund={quote(str(name))}" target="_self">{safe_name}</a>'


class FundNotFoundError(Exception):
    pass


@dataclass
class FinanceBot:
    df: pd.DataFrame = field(default=None, repr=False)

    def __post_init__(self):
        self.load_data()
        # Conversation state for the guided Asset Type -> Sub Category flow.
        # None when no guided flow is in progress.
        self.pending: dict | None = None

    # ------------------------------------------------------------------
    # Data loading -- always the fixed static file/sheet, no overrides.
    # ------------------------------------------------------------------
    def load_data(self) -> None:
        path = _data_path()
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Dataset not found at '{path}'. Make sure "
                f"'{DATA_FILENAME}' is in the same folder as "
                f"finance_bot.py (sheet: '{SHEET_NAME}')."
            )
        df = pd.read_excel(path, sheet_name=SHEET_NAME)
        df.columns = [c.strip() for c in df.columns]
        required = {"Scheme Name", "Sub Category", "Composite_Score"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Dataset is missing required columns: {missing}")
        self.df = df
        self._scheme_names = df["Scheme Name"].astype(str).tolist()
        self._sub_categories = sorted(df["Sub Category"].dropna().unique().tolist())

        # Build Asset Type -> [Sub Category, ...] mapping for the guided flow.
        if "Asset Class" in df.columns:
            self._asset_types = sorted(df["Asset Class"].dropna().unique().tolist())
            self._asset_type_to_subcats = {
                asset: sorted(
                    df.loc[df["Asset Class"] == asset, "Sub Category"]
                    .dropna().unique().tolist()
                )
                for asset in self._asset_types
            }
        else:
            # No Asset Class column -> treat everything as one bucket.
            self._asset_types = ["All Funds"]
            self._asset_type_to_subcats = {"All Funds": self._sub_categories}

    @property
    def sub_categories(self) -> list[str]:
        return self._sub_categories

    @property
    def asset_types(self) -> list[str]:
        return self._asset_types

    @property
    def asset_type_to_subcats(self) -> dict[str, list[str]]:
        return self._asset_type_to_subcats

    def fund_count(self) -> int:
        return len(self.df)

    # ------------------------------------------------------------------
    # Sub-category matching -- fuzzy, highest-score based (no exact text
    # required). Matching always runs against the raw dataset values.
    # Returns the best matching (raw) Sub Category and its score.
    # ------------------------------------------------------------------
    def best_sub_category_match(
        self, query: str, candidates: list[str] | None = None
    ) -> tuple[str | None, float]:
        q = (query or "").strip().lower()
        if not q:
            return None, 0.0

        pool = candidates if candidates is not None else self._sub_categories
        if not pool:
            return None, 0.0

        best_sc, best_score = None, 0.0
        for sc in pool:
            sc_l = sc.lower()
            if sc_l == q:
                return sc, 1.0

            score = difflib.SequenceMatcher(None, q, sc_l).ratio()
            # Boost substring matches (e.g. "large cap" inside "Large Cap Fund")
            if q in sc_l or sc_l.replace(" fund", "").strip() in q:
                score = max(score, 0.85)

            if score > best_score:
                best_sc, best_score = sc, score

        return best_sc, best_score

    def match_sub_categories(self, query: str, limit: int = 3) -> list[str]:
        """Kept for backward compatibility: returns a short ranked list
        of raw Sub Category values."""
        q = query.strip().lower()
        if not q:
            return []
        scored = []
        for sc in self._sub_categories:
            sc_l = sc.lower()
            score = difflib.SequenceMatcher(None, q, sc_l).ratio()
            if q in sc_l or sc_l.replace(" fund", "").strip() in q:
                score = max(score, 0.85)
            scored.append((sc, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [sc for sc, sc_score in scored[:limit] if sc_score > 0]

    # ------------------------------------------------------------------
    # Fund name matching
    # ------------------------------------------------------------------
    def match_fund(self, query: str) -> pd.Series:
        q = query.strip().lower()
        if not q:
            raise FundNotFoundError("No fund name given.")

        exact = self.df[self.df["Scheme Name"].str.lower() == q]
        if len(exact):
            return exact.iloc[0]

        contains = self.df[self.df["Scheme Name"].str.lower().str.contains(re.escape(q), na=False)]
        if len(contains):
            contains = contains.assign(_len=contains["Scheme Name"].str.len()).sort_values("_len")
            return contains.iloc[0]

        close = difflib.get_close_matches(query, self._scheme_names, n=1, cutoff=0.45)
        if close:
            return self.df[self.df["Scheme Name"] == close[0]].iloc[0]

        raise FundNotFoundError(f"No fund matching '{query}' found in the dataset.")

    def match_funds_multi(self, query: str, n: int = 5) -> pd.DataFrame:
        """Return several close candidates (used when an exact pick is ambiguous)."""
        q = query.strip().lower()
        contains = self.df[self.df["Scheme Name"].str.lower().str.contains(re.escape(q), na=False)]
        if len(contains):
            return contains.head(n)
        close = difflib.get_close_matches(query, self._scheme_names, n=n, cutoff=0.4)
        return self.df[self.df["Scheme Name"].isin(close)]

    # ------------------------------------------------------------------
    # Top-N funds in a sub-category
    # ------------------------------------------------------------------
    def top_funds(self, sub_category: str, n: int = 10, sort_by: str = "Peer_Rank") -> pd.DataFrame:
        subset = self.df[self.df["Sub Category"] == sub_category].copy()
        if subset.empty:
            return subset
        subset = dedup_funds(subset)
        if "Peer_Rank" in subset.columns:
            subset["Peer_Rank"]=pd.to_numeric(subset["Peer_Rank"],errors="coerce")
            subset=subset.dropna(subset=["Peer_Rank"])
            subset=subset[subset["Peer_Rank"]<=n]
            return subset.sort_values(["Peer_Rank","Composite_Score"],ascending=[True,False])
        if sort_by not in subset.columns:
            sort_by="Composite_Score"
        return subset.sort_values(sort_by,ascending=False).head(n)

    # ------------------------------------------------------------------
    # Formatting: top-N table -> markdown
    # ------------------------------------------------------------------
    def format_top_funds(self, sub_category: str, n: int = 10) -> str:
        subset = self.top_funds(sub_category, n=n)
        if subset.empty:
            return f"I couldn't find any funds in **{clean_subcat_label(sub_category)}**."

        cols = [c for c in TOP_N_TABLE_COLS if c in subset.columns]
        lines = [f"### Top {n} Peer Ranks in **{clean_subcat_label(sub_category)}** ({len(subset)} funds)\n"]
        header = "| # | " + " | ".join(cols) + " |"
        sep = "|---|" + "|".join(["---"] * len(cols)) + "|"
        lines += [header, sep]
        for i, (_, row) in enumerate(subset.iterrows(), start=1):
            vals = []
            for c in cols:
                v = row[c]
                if c == "Scheme Name":
                    v = _fund_link(v)
                elif isinstance(v, float):
                    if c in PERCENT_COLS:
                        v = f"{v * 100:.2f}%"
                    else:
                        v = f"{v:.2f}"
                vals.append(str(v))
            lines.append(f"| {i} | " + " | ".join(vals) + " |")
        lines.append(
            "\n_Ranked by Composite Score (blends 3Y return, risk-adjusted "
            "return, drawdown & volatility percentile vs. category peers). "
            "Ask 'tell me about <fund name>' for the full metric sheet on any of these._"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Formatting: full fund profile -> markdown
    # ------------------------------------------------------------------
    def format_fund_profile(self, row: pd.Series) -> str:
        def fmt(v, is_subcat_field=False, is_percent=False):
            if pd.isna(v):
                return "—"
            if is_subcat_field:
                return clean_subcat_label(str(v))
            if isinstance(v, float):
                if is_percent:
                    return f"{v * 100:.2f}%"
                return f"{v:.2f}"
            return str(v)

        out = [f"## {row['Scheme Name']}\n"]

        out.append("**Basic Information**")
        out.append("| Field | Value |")
        out.append("|---|---|")
        for c in BASIC_COLS:
            if c in row.index and c != "Scheme Name":
                out.append(f"| {c} | {fmt(row[c], is_subcat_field=(c == 'Sub Category'))} |")
        out.append("")

        out.append("**Costs**")
        out.append("| Field | Value |")
        out.append("|---|---|")
        for c in COST_COLS:
            if c in row.index:
                out.append(f"| {c} | {fmt(row[c])} |")
        out.append("")

        for horizon in HORIZONS:
            present = [f"{horizon}_{s}" for s in METRIC_SUFFIXES if f"{horizon}_{s}" in row.index]
            if not present:
                continue
            out.append(f"**{horizon} Performance & Risk**")
            out.append("| Metric | Value |")
            out.append("|---|---|")
            for c in present:
                suffix = c.split("_", 1)[1]
                label = FRIENDLY_LABELS.get(suffix, suffix)
                out.append(f"| {label} | {fmt(row[c], is_percent=(suffix == 'CAGR'))} |")
            out.append("")

        pctile_present = [c for c in PEER_PCTILE_COLS if c in row.index]
        if pctile_present:
            out.append("**Peer Percentile Rank (3Y, within Sub Category)**")
            out.append("| Metric | Percentile |")
            out.append("|---|---|")
            for c in pctile_present:
                label = c.replace("3Y_", "").replace("_PeerPctile", "")
                label = FRIENDLY_LABELS.get(label, label)
                out.append(f"| {label} | {fmt(row[c])} |")
            out.append("")

        out.append("**Overall**")
        out.append("| Metric | Value |")
        out.append("|---|---|")
        for c in SCORE_COLS:
            if c in row.index:
                out.append(f"| {c.replace('_', ' ')} | {fmt(row[c])} |")

        return "\n".join(out)

    # ------------------------------------------------------------------
    # Guided "Asset Type -> Sub Category" flow
    # ------------------------------------------------------------------
    def _render_options_table(
        self, options: list[str], heading: str, clean: bool = False
    ) -> str:
        """Render a numbered options list as a single markdown table
        (instead of a bracketed '[1] ... [2] ...' list). If `clean` is
        True, each option's display text is passed through
        `clean_subcat_label` first (used for Sub Category options)."""
        lines = [f"### {heading}\n"]
        lines.append("| # | Option |")
        lines.append("|---|---|")
        for i, opt in enumerate(options, start=1):
            label = clean_subcat_label(opt) if clean else opt
            lines.append(f"| {i} | {label} |")
        lines.append(
            "\n_Tap an option in the panel, or reply with its number or name._"
        )
        return "\n".join(lines)

    def pending_options_payload(self) -> list[dict] | None:
        """Structured version of the current pending options, meant for a
        front end to render as real clickable buttons / a side-panel list
        (rather than parsing the markdown table). Each entry's 'value' is
        the exact string that should be sent back as the user's reply if
        that option is clicked; 'label' is the clean, display-ready text.
        Returns None if there's no guided flow in progress."""
        if not self.pending:
            return None
        stage = self.pending["stage"]
        options = self.pending.get("options", [])
        clean = stage == "await_sub_category"
        return [
            {
                "index": i,
                "label": clean_subcat_label(opt) if clean else opt,
                "value": opt,
            }
            for i, opt in enumerate(options, start=1)
        ]

    def start_asset_type_flow(self) -> str:
        self.pending = {"stage": "await_asset_type", "options": self._asset_types}
        return self._render_options_table(
            self._asset_types, "Which Asset Type are you interested in?"
        )

    def _resolve_choice(self, query: str, options: list[str]) -> str | None:
        """Resolve a user's reply against an option list: by index or by
        highest-similarity text match (against the raw values, so a reply
        of either the raw value or the cleaned display label works)."""
        q = query.strip()
        if q.isdigit():
            idx = int(q) - 1
            if 0 <= idx < len(options):
                return options[idx]
            return None
        best, score = self.best_sub_category_match(q, candidates=options)
        return best if score >= 0.3 else None

    def _handle_pending(self, query: str) -> str | None:
        """Advances the guided flow if one is in progress. Returns the
        response string, or None if there's no pending flow to handle."""
        if not self.pending:
            return None

        stage = self.pending["stage"]

        if stage == "await_asset_type":
            choice = self._resolve_choice(query, self.pending["options"])
            if choice is None:
                return (
                    "I didn't quite catch that. " +
                    self._render_options_table(self.pending["options"], "Please pick an Asset Type")
                )
            subcats = self._asset_type_to_subcats.get(choice, [])
            self.pending = {
                "stage": "await_sub_category",
                "asset_type": choice,
                "options": subcats,
            }
            if not subcats:
                self.pending = None
                return f"No Sub Categories found under **{choice}**."
            return self._render_options_table(
                subcats, f"Great — within {choice}, which Sub Category?", clean=True
            )

        if stage == "await_sub_category":
            options = self.pending["options"]
            choice = self._resolve_choice(query, options)
            if choice is None:
                # Fall back to a global best-match search in case the user
                # typed something close but not in this asset type's list.
                choice, score = self.best_sub_category_match(query)
                if choice is None or score < SUBCAT_MATCH_THRESHOLD:
                    return (
                        "I didn't quite catch that. " +
                        self._render_options_table(options, "Please pick a Sub Category", clean=True)
                    )
            self.pending = None
            return self.format_top_funds(choice, n=10)

        # Unknown stage -- reset defensively.
        self.pending = None
        return None

    # ------------------------------------------------------------------
    # Intent detection (rule based, no LLM required)
    # ------------------------------------------------------------------
    TOP_PATTERNS = [
        r"\btop\s*(\d+)?\s*(?:performing|rated|funds?)\b.*?\bin\b\s*(.+)",
        r"\bbest\s*(\d+)?\s*funds?\b.*?\bin\b\s*(.+)",
        r"\btop\s*(\d+)?\s*(.+?)\s*funds?\b",
    ]

    def detect_intent(self, query: str) -> tuple[str, dict]:
        q = query.strip()
        ql = q.lower()

        for pat in self.TOP_PATTERNS:
            m = re.search(pat, ql)
            if m:
                groups = m.groups()
                n = 10
                cat_text = None
                for g in groups:
                    if g and g.isdigit():
                        n = int(g)
                    elif g:
                        cat_text = g
                if cat_text:
                    cat_text = re.sub(r"\bfunds?\b", "", cat_text).strip(" ?.!")
                    return "top_funds", {"category_text": cat_text, "n": n}

        if any(kw in ql for kw in ["tell me about", "info on", "information about",
                                    "details of", "details on", "about the fund",
                                    "how is", "how's"]):
            for trigger in ["tell me about", "info on", "information about",
                             "details of", "details on", "about the fund", "how is", "how's"]:
                if trigger in ql:
                    idx = ql.index(trigger) + len(trigger)
                    return "fund_info", {"fund_text": q[idx:].strip(" ?.!")}

        # Explicit request to browse categories -> kick off the guided flow.
        if any(kw in ql for kw in ["show categories", "browse funds", "show funds",
                                    "which categories", "list categories",
                                    "top funds", "show me funds"]) and not self.match_sub_categories(q):
            return "browse", {}

        # Generic definitional/explainer questions ("what is...", "how does...",
        # "explain...") should never be treated as a category or fund lookup --
        # they're meant for the LLM fallback. Check this BEFORE the fuzzy
        # sub-category match below, since short generic text can otherwise
        # score a spuriously high similarity against an unrelated category name.
        generic_question = bool(re.match(
            r"^(what|why|how|explain|define|meaning of|difference between)\b", ql
        ))

        if not generic_question:
            best_sc, score = self.best_sub_category_match(q)
            if best_sc and score >= SUBCAT_MATCH_THRESHOLD:
                return "top_funds", {"category_text": q, "n": 10}

        if not generic_question:
            candidate = self.match_funds_multi(q, n=1)
            if not candidate.empty:
                return "fund_info", {"fund_text": q}

        return "unknown", {"raw": q}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def respond(self, query: str, llm_fallback=None) -> str:
        # If a guided Asset Type / Sub Category flow is in progress, handle
        # the reply first regardless of what it looks like.
        pending_response = self._handle_pending(query)
        if pending_response is not None:
            return pending_response

        intent, params = self.detect_intent(query)

        if intent == "browse":
            return self.start_asset_type_flow()

        if intent == "top_funds":
            best_sc, score = self.best_sub_category_match(params["category_text"])
            if not best_sc or score < SUBCAT_MATCH_THRESHOLD:
                # Couldn't confidently match free text -> guided flow.
                return self.start_asset_type_flow()
            return self.format_top_funds(best_sc, n=params.get("n", 10))

        if intent == "fund_info":
            try:
                row = self.match_fund(params["fund_text"])
                return self.format_fund_profile(row)
            except FundNotFoundError:
                candidates = self.match_funds_multi(params["fund_text"], n=5)
                if not candidates.empty:
                    names = "\n".join(
                        f"- {_fund_link(n)}" for n in candidates["Scheme Name"]
                    )
                    return f"I couldn't find an exact match. Did you mean:\n\n{names}"
                return (
                    f"I couldn't find a fund matching '{params['fund_text']}' in the dataset."
                )

        # Unknown intent -> optional LLM fallback (Groq) for general finance Q&A
        if llm_fallback is not None:
            return llm_fallback(query)

        # No LLM configured -> guide the user via Asset Type / Sub Category
        # buttons instead of dumping a flat list of categories.
        return (
            "I can help with two things right now:\n\n"
            "1. **Top performing funds** — pick a category below, or just type "
            "something like *\"top 10 mid cap funds\"*\n"
            "2. **Fund details** — e.g. *\"tell me about HDFC Flexi Cap Fund\"*\n\n"
            + self.start_asset_type_flow()
        )