"""
finance_bot.py
--------------
Core logic for FundGPT: an AI-powered mutual fund analytics chatbot.

Responsibilities:
  1. Load & validate the fund dataset from the fixed local file
     "MF_Risk_Metrics.xlsx" (sheet "Risk Metrics"), located in the same
     folder as this script. This is the ONLY data source the bot will ever
     read from -- there is no upload path, and the loader does not accept
     an alternate file or sheet name.
  2. Answer "top performing funds in <Sub Category>" queries, matching the
     user's category text against the dataset's real Sub Category values by
     highest similarity score (no need to type it exactly), and -- if an
     AMC / fund-house name is present in the query (e.g. "HDFC Small cap
     funds") -- filtering results down to just that AMC.
  3. Answer "tell me about <Scheme Name>" queries with the full metric sheet.
  4. Lightweight intent + entity extraction: regex for coarse intent
     shape ("top N ... in ...") combined with local, offline NLP
     (nlp_utils.py: spaCy tokenization + a dataset-driven AMC matcher,
     and rapidfuzz for fuzzy string scoring) for pulling the AMC name and
     the true category/fund text out of free-form phrasing. No LLM call
     is required for these two core features, and nothing in this path
     makes a network request.
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

Sub Category canonicalization
------------------------------
The raw dataset sometimes tags the *same* SEBI category under two
different spellings -- most notably ELSS appearing both as plain
"...(ELSS)" and as "...(ELSS Tax Saver)" / "...(ELSS Tax Saver Fund)".
Since every downstream feature (the sub-category matcher, the Asset
Type -> Sub Category browse map, and top_funds()) keys off the raw
"Sub Category" column verbatim, two spellings of the same category
would otherwise survive as two separate entries everywhere -- the
sidebar list, the guided-flow buttons, and top-N results. See
`_canonicalize_subcat`, which is applied once at load time so every
consumer downstream sees a single merged value instead.

NLP layer
---------
See nlp_utils.py for the local, offline NLP helpers this file uses:
  - AMCMatcher: recognizes an AMC / fund-house name anywhere in a query
    (built from the dataset's own "AMC (Fund House)" column -- never a
    hardcoded list) and strips it out, so "HDFC Small cap funds" splits
    cleanly into amc="HDFC" and rest="Small cap funds" instead of the
    AMC name silently diluting -- or being dropped from -- the category
    match.
  - best_fuzzy_match / ranked_fuzzy_matches: rapidfuzz-based fuzzy
    scoring (replaces the previous difflib.SequenceMatcher calls).
    rapidfuzz's token_sort_ratio / token_set_ratio compare bags of
    words rather than raw character sequences, so word reordering and
    a few extra/missing words -- exactly what stripping (or failing to
    strip) an AMC prefix introduces -- no longer tank the score.
This is a fully local/offline NLP layer: spaCy + rapidfuzz only, no
external API calls, no added latency or cost per query.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import pandas as pd

from rapidfuzz import fuzz

from nlp_utils import (
    AMCMatcher,
    best_fuzzy_match,
    extract_number_word,
    fuzzy_ratio,
    ranked_fuzzy_matches,
)

# ----------------------------------------------------------------------
# Fixed dataset location -- this is the single, static source of data.
# There is intentionally no way to point the bot at a different file,
# a different sheet, or an uploaded workbook.
# ----------------------------------------------------------------------

DATA_FILENAME = "MF_Risk_Metrics.xlsx"
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
# NOTE: these are kept in sync with the actual columns produced by
# mf_risk_metrics.py. There is no TER / cost data in that workbook, so
# there is deliberately no "Costs" section here -- rendering one would
# just show blank/"--" rows for every fund.

BASIC_COLS = [
    "Scheme Code", "Scheme Name", "AMC (Fund House)", "Sub Category",
    "Asset Class", "ELSS", "Latest NAV Date", "Latest NAV",
]

HORIZONS = ["1D", "1W", "1M", "6M", "1Y", "3Y", "5Y", "10Y", "SI"]
METRIC_SUFFIXES = [
    "AbsoluteReturn", "CAGR", "Volatility", "MaxDrawdown", "Sharpe", "Sortino",
    "DownsideDev", "VaR95", "Calmar", "RollMean", "RollMin", "RollMax",
]
PEER_PCTILE_COLS = [
    "3Y_CAGR_PeerPctile", "3Y_Sharpe_PeerPctile", "3Y_Sortino_PeerPctile",
    "3Y_Calmar_PeerPctile", "3Y_MaxDrawdown_PeerPctile", "3Y_Volatility_PeerPctile",
    "3Y_VaR95_PeerPctile", "3Y_DownsideDev_PeerPctile",
]
SCORE_COLS = ["Composite_Score", "Peer_Rank"]

# ----------------------------------------------------------------------
# Top-N table columns -- Observed (absolute, non-annualised) Return at
# each horizon, NOT CAGR, and no Peer_Rank column shown (Peer_Rank is
# still what the table is ORDERED by -- see top_funds() -- it's just not
# rendered as a column anymore).
#
# Each entry is (source_col, fallback_col_or_None, display_label). The
# fallback is only used if the primary "Obs return" column isn't present
# in the loaded sheet for that horizon, so the table still degrades
# gracefully instead of silently dropping a horizon.
# ----------------------------------------------------------------------
TOP_N_METRIC_SPECS = [
    ("1D_AbsoluteReturn", None, "1D Obs. Return"),
    ("6M_AbsoluteReturn", None, "6M Obs. Return"),
    ("1Y_AbsoluteReturn", "1Y_CAGR", "1Y Obs. Return"),
    ("3Y_AbsoluteReturn", "3Y_CAGR", "3Y Obs. Return"),
    ("5Y_AbsoluteReturn", "5Y_CAGR", "5Y Obs. Return"),
]

# These columns are stored as fractions (0.04 == 4%) and are rendered with
# a trailing '%' in the Top-N table.
PERCENT_COLS = {
    "1D_AbsoluteReturn", "6M_AbsoluteReturn", "1Y_AbsoluteReturn",
    "3Y_AbsoluteReturn", "5Y_AbsoluteReturn", "1Y_CAGR", "3Y_CAGR", "5Y_CAGR",
}

FRIENDLY_LABELS = {
    "AbsoluteReturn": "Absolute Return",
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
# Sub Category canonicalization -- merge known duplicate raw spellings
# ----------------------------------------------------------------------
# The dataset can tag the SAME SEBI category under different raw
# "Sub Category" strings. Left unmerged, this shows up as duplicate
# entries in the browse list and splits a single category's funds
# across two separate _funds() results. This runs once at load time
# (see FinanceBot.load_data), before _sub_categories / the Asset Type
# map are built, so every downstream consumer sees one merged value.
#
# Known duplicate: ELSS vs. "ELSS Tax Saver" / "ELSS Tax Saver Fund" --
# same category, two spellings. Add further phrase-merge rules here if
# more duplicates like this turn up in the sheet.
_ELSS_VARIANT_RE = re.compile(
    r"elss(\s*-?\s*tax\s*saver(\s*fund)?)?", re.IGNORECASE
)


def _canonicalize_subcat(raw):
    """Collapse known duplicate raw Sub Category spellings onto one
    canonical value. Preserves whatever wrapper the row already has
    ('Open Ended Schemes(...)' etc.) -- only the inner category phrase
    is normalized, so matching against the rest of the dataset (and the
    wrapper-stripping helpers below) still works unchanged."""
    if not isinstance(raw, str):
        return raw
    if "elss" in raw.lower():
        return _ELSS_VARIANT_RE.sub("ELSS", raw)
    return raw


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
_OPTION_PHRASES = [
    # Longer, descriptive variants FIRST -- these are the newer full-length
    # payout-option names funds have started using instead of the short
    # "IDCW" / "Dividend" suffix, e.g. "SBI Contra Fund - Direct Plan -
    # Income Distribution cum Capital Withdrawal Option (IDCW)". Stripping
    # only the bare word "idcw" leaves the rest of this phrase behind,
    # which then fails to match the Growth variant's key and lets both
    # rows survive dedup -- checked here explicitly to avoid that.
    "payout & re-investment of income distribution cum capital withdrawal option",
    "payout and re-investment of income distribution cum capital withdrawal option",
    "income distribution cum capital withdrawal option",
    "idcw", "dividend", "growth", "payout", "reinvestment", "bonus",
]
# Backward-compatible alias.
_OPTION_KEYWORDS = _OPTION_PHRASES


def _fund_dedup_key(name: str) -> str:
    """Normalized identity for a fund, with the plan-option phrase (Growth /
    IDCW / Income Distribution cum Capital Withdrawal Option / Dividend /
    ...) stripped out so different options of the same underlying fund
    collapse to the same key. 'Direct'/'Regular Plan' is deliberately kept,
    since those ARE genuinely different funds/TERs."""
    text = str(name).lower()
    for phrase in _OPTION_PHRASES:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    # Leftover punctuation from a fully-stripped phrase, e.g. "(  )" or
    # a trailing "- -", would otherwise stop two variants' keys matching.
    text = re.sub(r"[()]", " ", text)
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


# Scheme-type prefixes stripped only for BROWSE-LIST display (see
# subcat_browse_label below) -- kept separate from clean_subcat_label
# because the Top-N table header and a fund's full profile still want
# the scheme-type shown (they aren't rendered inside an Asset-Type-
# scoped list, so "Contra Fund" alone would lose useful context there).
# Longer/more specific phrases are listed first so e.g. "equity schemes"
# matches before the shorter "equity scheme" would partially match it.
_SCHEME_TYPE_PREFIXES = [
    "income/debt oriented schemes",
    "exchange traded funds etfs",
    "overseas fund of funds",
    "solution oriented scheme",
    "debt schemes", "debt scheme",
    "equity schemes", "equity scheme",
    "hybrid schemes", "hybrid scheme",
    "index funds",
    "other scheme",
]


def strip_scheme_type_prefix(label: str) -> str:
    """Remove a leading 'Debt Scheme - ' / 'Equity Scheme - ' / ... style
    prefix from an already wrapper-cleaned Sub Category label. Falls
    back to the original label if nothing would be left after stripping
    (e.g. a bare 'Equity Scheme' with no specific fund type), so an
    option is never shown blank."""
    text = str(label)
    text_l = text.lower()
    for prefix in _SCHEME_TYPE_PREFIXES:
        if text_l.startswith(prefix):
            rest = text[len(prefix):].lstrip(" -")
            return rest or text
    return text


def subcat_browse_label(raw: str) -> str:
    """Display label for a Sub Category when it's shown as an option
    inside an Asset-Type-scoped browse list (the guided flow buttons /
    the sidebar's Step 2 list): both the 'Open/Close Ended Schemes'
    wrapper AND the redundant scheme-type prefix are stripped, since the
    Asset Type is already implied by which list the option is in --
    e.g. 'Equity Scheme - Contra Fund' -> 'Contra Fund' when it's
    already under the "Equity" list. Used as the dedup key when building
    that list too, so a scheme-prefixed and a bare variant that reduce
    to the same short label (e.g. "Equity Scheme - ELSS" and "ELSS")
    collapse to one option instead of showing as two identical entries."""
    return strip_scheme_type_prefix(clean_subcat_label(raw))


# ----------------------------------------------------------------------
# Free-text category matching helpers
# ----------------------------------------------------------------------
def _normalize_category_text(text: str) -> str:
    """Lowercase + collapse whitespace + singularize the standalone word
    'funds' -> 'fund' so a plural user query ('small cap funds') and a
    singular dataset label ('Small Cap Fund') aren't treated as different
    strings by an exact-substring check purely over the trailing 's'."""
    t = str(text or "").lower().strip()
    t = re.sub(r"\bfunds\b", "fund", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ----------------------------------------------------------------------
# Asset Type -> Sub Category mapping for the guided "Browse by Category"
# flow.
# ----------------------------------------------------------------------
# Two separate problems showed up here:
#
#   1. DUPLICATES: the raw sheet can contain multiple different raw Sub
#      Category strings that all clean down to the *same* display label
#      -- most commonly an "Open Ended Schemes(X)" row and a "Close Ended
#      Schemes(X)" row both collapsing to just "X" via
#      clean_subcat_label(). Building the browse list from raw unique
#      values let both survive as separate list entries, so the same
#      label appeared twice under one Asset Type. (A related case --
#      ELSS vs. "ELSS Tax Saver" -- is handled earlier, upstream of this,
#      by _canonicalize_subcat() in load_data(), since those two raw
#      strings don't even clean down to the same text on their own.)
#
#   2. MISPLACEMENT: grouping by the sheet's "Asset Class" column trusts
#      that column to be tagged correctly per row. In practice it isn't
#      -- e.g. many "Debt Scheme - ..." / "Hybrid Scheme - ..." /
#      "Solution Oriented Scheme - ..." rows turned out to be tagged
#      Asset Class = "Equity", which then made ALL of those categories
#      surface under the "Equity" bucket instead of their real one.
#
# The fix for both: classify each Sub Category by the SEBI scheme-type
# phrase already embedded in its own text ("Debt Scheme - ...",
# "Equity Scheme - ...", "Hybrid Scheme - ...", "Index Funds - ...",
# "Solution Oriented Scheme - ...", "Other Scheme - ..."), which is
# self-describing and doesn't depend on a separate column that can be
# mistagged. The "Asset Class" column is used only as a fallback for the
# handful of legacy labels ("ELSS", "Growth", "Income", ...) that carry
# no scheme-type phrase of their own.
_ASSET_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Solution Oriented", ["solution oriented"]),
    ("Index ETF", ["index fund", "exchange traded fund", "etf"]),
    ("Hybrid", ["hybrid scheme"]),
    ("Equity", ["equity scheme", "elss"]),
    ("Debt", ["debt scheme", "income/debt oriented", "il&fs", "idf", "income"]),
    ("Other", ["other scheme", "fund of funds"]),
]


def _infer_asset_type(raw_subcat: str) -> str | None:
    """Classify a raw Sub Category string by the scheme-type phrase
    embedded in its own text. Returns None if no known phrase is found,
    so the caller can fall back to the row's "Asset Class" value."""
    text = str(raw_subcat).lower()
    for asset_type, keywords in _ASSET_TYPE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return asset_type
    return None


def _build_asset_type_subcat_map(
    df: pd.DataFrame, asset_types: list[str]
) -> dict[str, list[str]]:
    """Build Asset Type -> [Sub Category, ...] for the guided browse
    flow. Each cleaned display label is collapsed to a single
    representative raw value per Asset Type (fixes duplicates), and each
    Sub Category is bucketed by its own embedded scheme-type phrase
    rather than the sheet's "Asset Class" column (fixes misplacement)."""
    # asset_type -> {cleaned_label: (raw_value_with_max_count, fund_count)}
    buckets: dict[str, dict[str, tuple[str, int]]] = {a: {} for a in asset_types}

    counts = df.groupby(["Asset Class", "Sub Category"]).size()
    for (asset_class, raw_subcat), count in counts.items():
        asset_type = _infer_asset_type(raw_subcat) or asset_class
        by_label = buckets.setdefault(asset_type, {})
        label = subcat_browse_label(raw_subcat)
        current = by_label.get(label)
        if current is None or count > current[1]:
            by_label[label] = (raw_subcat, count)

    result: dict[str, list[str]] = {}
    for asset_type, by_label in buckets.items():
        raws = [raw for raw, _ in by_label.values()]
        result[asset_type] = sorted(raws, key=subcat_browse_label)

    return result


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

        # Strip stray leading/trailing whitespace from the text fields the
        # guided browse flow groups on. Untrimmed whitespace (e.g. a sheet
        # value of "Equity " next to "Equity") would otherwise be treated
        # as a distinct value and produce the same duplicate/misplaced
        # symptom as the Open/Close-Ended wrapper issue below.
        for col in ("Sub Category", "Asset Class"):
            if col in df.columns:
                df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)

        # Merge known duplicate Sub Category spellings (e.g. plain "ELSS"
        # vs. "ELSS Tax Saver" / "ELSS Tax Saver Fund") onto one canonical
        # value. This MUST run before _sub_categories / the Asset Type map
        # are built below, since everything downstream keys off this
        # column verbatim.
        if "Sub Category" in df.columns:
            df["Sub Category"] = df["Sub Category"].apply(_canonicalize_subcat)

        self.df = df
        self._scheme_names = df["Scheme Name"].astype(str).tolist()
        self._sub_categories = sorted(df["Sub Category"].dropna().unique().tolist())

        # Build Asset Type -> [Sub Category, ...] mapping for the guided flow.
        if "Asset Class" in df.columns:
            self._asset_types = sorted(df["Asset Class"].dropna().unique().tolist())
            self._asset_type_to_subcats = _build_asset_type_subcat_map(df, self._asset_types)
        else:
            # No Asset Class column -> treat everything as one bucket.
            self._asset_types = ["All Funds"]
            self._asset_type_to_subcats = {"All Funds": self._sub_categories}

        # Local NLP: AMC / fund-house matcher, built from the dataset's own
        # "AMC (Fund House)" column values -- never a hardcoded list -- so
        # a query like "HDFC Small cap funds" can have "HDFC" recognized
        # and split off from the category text instead of silently
        # diluting (or being dropped from) the fuzzy category match. See
        # nlp_utils.AMCMatcher and _extract_amc_and_rest() below.
        if "AMC (Fund House)" in df.columns:
            amc_values = df["AMC (Fund House)"].dropna().astype(str).unique().tolist()
        else:
            amc_values = []
        self._amc_matcher = AMCMatcher(amc_values)

        # Kept for backward compatibility with any external code that
        # imported this attribute directly; AMCMatcher now does the actual
        # extraction work.
        self._amc_first_words: set[str] = set(self._amc_matcher._brand_words)

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
    # AMC extraction -- pulls a recognized AMC / fund-house name out of
    # free text and returns (amc_or_None, remaining_text). Delegates to
    # nlp_utils.AMCMatcher, which is seeded from the dataset itself.
    # ------------------------------------------------------------------
    def _extract_amc_and_rest(self, query: str) -> tuple[str | None, str]:
        return self._amc_matcher.extract(query)

    def _funds_for_amc(self, subset: pd.DataFrame, amc_text: str) -> pd.DataFrame:
        """Filter `subset` down to rows whose AMC (Fund House) best matches
        `amc_text` (fuzzy, since a query's "HDFC" needs to match a full
        column value like "HDFC Mutual Fund"). Returns the filtered rows,
        or an empty frame if no AMC in the subset scores above threshold."""
        amc_col = "AMC (Fund House)"
        if amc_col not in subset.columns or subset.empty:
            return subset.iloc[0:0]
        amc_values = subset[amc_col].dropna().astype(str).unique().tolist()
        # token_set_ratio (not the default token_sort_ratio) here: the
        # query is a short brand word ("HDFC") being matched against a
        # much longer full legal name ("HDFC Mutual Fund"). token_set_ratio
        # scores a query whose words are a subset of the candidate's words
        # highly regardless of the length difference; token_sort_ratio
        # penalizes that length mismatch and would wrongly score this low
        # (verified: 'HDFC' vs 'HDFC Mutual Fund' -> 40% on token_sort_ratio
        # but 100% on token_set_ratio).
        best, score = best_fuzzy_match(amc_text, amc_values, scorer=fuzz.token_set_ratio)
        if best is None or score < 0.6:
            return subset.iloc[0:0]
        return subset[subset[amc_col] == best]

    # ------------------------------------------------------------------
    # Sub-category matching -- fuzzy, highest-score based (no exact text
    # required). Matching runs against the *cleaned* display label (the
    # "Open/Close Ended Schemes(...)" wrapper stripped out), not the raw
    # dataset string. Comparing against the raw value let its wrapper text
    # dilute the old character-sequence ratio -- a long, correct raw value
    # like "Open Ended Schemes(Equity Scheme - Small Cap Fund)" could
    # score WORSE against a short query than an unrelated but
    # coincidentally short raw label with no scheme-type prefix (e.g.
    # "Open Ended Schemes(IL&FS Mutual Fund IDF)"), purely because of
    # string-length mismatch, not actual relevance. The raw Sub Category
    # value is still what gets returned/used for filtering -- only the
    # comparison text changes.
    #
    # Scoring uses rapidfuzz's token_sort_ratio (nlp_utils.fuzzy_ratio) --
    # a bag-of-words comparison, unlike difflib's raw character-sequence
    # ratio -- so a query with extra words still scores well against the
    # right label as long as the important words match.
    # Returns the best matching (raw) Sub Category and its score.
    # ------------------------------------------------------------------
    def best_sub_category_match(
        self, query: str, candidates: list[str] | None = None
    ) -> tuple[str | None, float]:
        q = _normalize_category_text(query)
        if not q:
            return None, 0.0

        pool = candidates if candidates is not None else self._sub_categories
        if not pool:
            return None, 0.0

        best_sc, best_score = None, 0.0
        for sc in pool:
            label_l = _normalize_category_text(clean_subcat_label(sc))
            if label_l == q:
                return sc, 1.0

            score = fuzzy_ratio(q, label_l)
            # Boost substring matches (e.g. "large cap" inside "Large Cap
            # Fund", or "small cap fund" -- after pluralization is
            # normalized above -- inside "Small Cap Fund").
            if q in label_l or label_l.replace(" fund", "").strip() in q:
                score = max(score, 0.85)

            if score > best_score:
                best_sc, best_score = sc, score

        return best_sc, best_score

    def match_sub_categories(self, query: str, limit: int = 3) -> list[str]:
        """Kept for backward compatibility: returns a short ranked list
        of raw Sub Category values. Uses the same cleaned-label / plural-
        normalized comparison as best_sub_category_match() so results here
        stay consistent with what a single lookup would pick."""
        q = _normalize_category_text(query)
        if not q:
            return []
        scored = []
        for sc in self._sub_categories:
            label_l = _normalize_category_text(clean_subcat_label(sc))
            score = fuzzy_ratio(q, label_l)
            if q in label_l or label_l.replace(" fund", "").strip() in q:
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

        best, score = best_fuzzy_match(query, self._scheme_names)
        if best is not None and score >= 0.45:
            return self.df[self.df["Scheme Name"] == best].iloc[0]

        raise FundNotFoundError(f"No fund matching '{query}' found in the dataset.")

    def match_funds_multi(self, query: str, n: int = 5) -> pd.DataFrame:
        """Return several close candidates (used when an exact pick is ambiguous)."""
        q = query.strip().lower()
        contains = self.df[self.df["Scheme Name"].str.lower().str.contains(re.escape(q), na=False)]
        if len(contains):
            return contains.head(n)
        matches = ranked_fuzzy_matches(query, self._scheme_names, limit=n, score_cutoff=0.4)
        names = [name for name, _score in matches]
        return self.df[self.df["Scheme Name"].isin(names)]

    def match_funds_ranked(self, query: str, n: int = 6) -> pd.DataFrame:
        """Rank every fund in the dataset by similarity to a free-text
        search and return up to n rows, best match first. Used so a fund
        search always surfaces every close candidate for the user to pick
        from -- instead of silently auto-selecting whichever single match
        scores highest, which can guess wrong when several funds share
        very similar names (different AMCs' "... ELSS Tax Saver Fund",
        Direct vs Regular plan, Growth vs IDCW, etc.).

        Uses rapidfuzz's token_set_ratio, which treats the query and each
        scheme name as bags of words -- so a short query like "hdfc flexi
        cap" scores well against the much longer "HDFC Flexi Cap Fund -
        Direct Plan - Growth" without needing a manual substring-boost
        special case."""
        q = (query or "").strip()
        if not q:
            return self.df.iloc[0:0]

        # A higher bar than the Sub Category matcher's (0.35): fund names
        # share a lot of boilerplate ("Fund", "Direct Plan", "Growth"), so
        # a loose cutoff pulls in unrelated AMCs' funds just because they're
        # in the same category (e.g. searching "SBI Flexi Cap Fund" would
        # otherwise also surface every other house's Flexi Cap fund). 0.55
        # keeps genuine near-duplicates (same fund, different plan/option)
        # while dropping same-category noise.
        matches = ranked_fuzzy_matches(q, self._scheme_names, limit=n, score_cutoff=0.55)
        if not matches:
            return self.df.iloc[0:0]
        ordered_names = [name for name, _score in matches]
        # Preserve rank order (rapidfuzz already sorts best-first, but
        # DataFrame.isin() doesn't preserve it) and dedupe if the same
        # scheme name appears more than once in the raw data.
        rows = self.df[self.df["Scheme Name"].isin(ordered_names)]
        rows = rows.drop_duplicates(subset="Scheme Name")
        rank = {name: i for i, name in enumerate(ordered_names)}
        rows = rows.assign(_rank=rows["Scheme Name"].map(rank)).sort_values("_rank")
        return rows.drop(columns="_rank").head(n)

    # ------------------------------------------------------------------
    # Top-N funds in a sub-category
    # ------------------------------------------------------------------
    def top_funds(
        self, sub_category: str, n: int = 10, sort_by: str = "Peer_Rank",
        amc: str | None = None,
    ) -> pd.DataFrame:
        subset = self.df[self.df["Sub Category"] == sub_category].copy()
        if subset.empty:
            return subset

        # Filter to a specific AMC / fund house before dedup/ranking, if
        # one was recognized in the query (e.g. "HDFC Small cap funds").
        if amc:
            subset = self._funds_for_amc(subset, amc)
            if subset.empty:
                return subset

        subset = dedup_funds(subset)

        # Only one fund per AMC in the displayed set -- if two funds from the
        # same fund house both qualify, keep just the better-ranked one
        # rather than showing the AMC twice. Skipped when the caller has
        # already filtered to a single AMC (amc is set), since collapsing
        # to "one per AMC" there would incorrectly cut an AMC's results
        # down to a single fund.
        #
        # This IS a backfill: the table always fills to n funds (subject to
        # there being n distinct-AMC funds in the category at all) by
        # walking down the ascending Peer_Rank / Composite_Score order past
        # rank n if dropping same-AMC and same-underlying-fund duplicates
        # left the top-n band short. Peer_Rank itself is not shown as a
        # column in the rendered table (see format_top_funds /
        # TOP_N_METRIC_SPECS) -- it's used here purely as the backend
        # ordering, ascending (best rank first).
        amc_col = "AMC (Fund House)" if ("AMC (Fund House)" in subset.columns and not amc) else None

        if "Peer_Rank" in subset.columns:
            subset["Peer_Rank"] = pd.to_numeric(subset["Peer_Rank"], errors="coerce")
            subset = subset.dropna(subset=["Peer_Rank"])
            subset = subset.sort_values(["Peer_Rank", "Composite_Score"], ascending=[True, False])
            if amc_col:
                subset = subset.drop_duplicates(subset=amc_col, keep="first")
            return subset.head(n)
        if sort_by not in subset.columns:
            sort_by = "Composite_Score"
        subset = subset.sort_values(sort_by, ascending=False)
        if amc_col:
            subset = subset.drop_duplicates(subset=amc_col, keep="first")
        return subset.head(n)

    # ------------------------------------------------------------------
    # Formatting: top-N table -> markdown
    # ------------------------------------------------------------------
    def _resolve_top_n_metric_cols(self, subset: pd.DataFrame) -> list[tuple[str, str]]:
        """For each entry in TOP_N_METRIC_SPECS, pick whichever of
        (primary, fallback) column actually exists in this dataset and
        pair it with its display label. Horizons with neither column
        present are skipped entirely rather than rendered blank."""
        resolved = []
        for primary, fallback, label in TOP_N_METRIC_SPECS:
            if primary in subset.columns:
                resolved.append((primary, label))
            elif fallback and fallback in subset.columns:
                resolved.append((fallback, label))
        return resolved

    def format_top_funds(self, sub_category: str, n: int = 10, amc: str | None = None) -> str:
        subset = self.top_funds(sub_category, n=n, amc=amc)
        cat_label = clean_subcat_label(sub_category)
        if subset.empty:
            if amc:
                return f"I couldn't find any **{amc}** funds in **{cat_label}**."
            return f"I couldn't find any funds in **{cat_label}**."

        metric_cols = self._resolve_top_n_metric_cols(subset)
        headers = ["Scheme Name"] + [label for _, label in metric_cols]
        heading = f"### Top performing funds in **{cat_label}**"
        if amc:
            heading += f" — **{amc}**"
        heading += f" ({len(subset)} funds)\n"
        lines = [heading]
        header = "| # | " + " | ".join(headers) + " |"
        sep = "|---|" + "|".join(["---"] * len(headers)) + "|"
        lines += [header, sep]
        for i, (_, row) in enumerate(subset.iterrows(), start=1):
            vals = [_fund_link(row["Scheme Name"])]
            for col, _label in metric_cols:
                v = row[col]
                if pd.isna(v):
                    v = "—"
                elif isinstance(v, float):
                    if col in PERCENT_COLS:
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
                is_pct = suffix in ("AbsoluteReturn", "CAGR")
                out.append(f"| {label} | {fmt(row[c], is_percent=is_pct)} |")
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
    def _render_prompt(self, heading: str) -> str:
        """Just the guided-flow question text -- no options list. The
        actual choices are rendered as real tappable buttons right below
        this message (see pending_options_payload() / app.py's button
        row), so repeating them here as a markdown table would just show
        every option twice."""
        return f"### {heading}\n\n_Tap an option below, or reply with its number or name._"

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
                "label": subcat_browse_label(opt) if clean else opt,
                "value": opt,
            }
            for i, opt in enumerate(options, start=1)
        ]

    def start_asset_type_flow(self) -> str:
        self.pending = {"stage": "await_asset_type", "options": self._asset_types}
        return self._render_prompt("Which Asset Type are you interested in?")

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
                    self._render_prompt("Please pick an Asset Type")
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
            return self._render_prompt(f"Great — within {choice}, which Sub Category?")

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
                        self._render_prompt("Please pick a Sub Category")
                    )
            self.pending = None
            return self.format_top_funds(choice, n=10)

        if stage == "await_fund_choice":
            options = self.pending["options"]
            choice = self._resolve_choice(query, options)
            if choice is None:
                return (
                    "I didn't quite catch that. " +
                    self._render_prompt("Please pick a fund")
                )
            self.pending = None
            match = self.df[self.df["Scheme Name"] == choice]
            if match.empty:
                return f"I couldn't find '{choice}' in the dataset."
            return self.format_fund_profile(match.iloc[0])

        # Unknown stage -- reset defensively.
        self.pending = None
        return None

    # ------------------------------------------------------------------
    # Intent detection (rule based, no LLM required) + local NLP entity
    # extraction (AMC name, category text, spelled-out counts).
    # ------------------------------------------------------------------
    TOP_PATTERNS = [
        r"\btop\s*(\d+)?\s*(?:performing|rated|funds?)\b.*?\bin\b\s*(.+)",
        r"\bbest\s*(\d+)?\s*funds?\b.*?\bin\b\s*(.+)",
        r"\btop\s*(\d+)?\s*(.+?)\s*funds?\b",
    ]

    def detect_intent(self, query: str) -> tuple[str, dict]:
        q = query.strip()

        # Strip a recognized AMC name off the query FIRST, before any
        # pattern matching or fuzzy category matching runs, so:
        #  (a) the AMC never dilutes/distracts the category fuzzy match, and
        #  (b) it's captured explicitly (params["amc"]) so top_funds() can
        #      actually filter by it, instead of being silently discarded.
        amc, q_wo_amc = self._extract_amc_and_rest(q)
        ql = q_wo_amc.lower()

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
                if cat_text is None:
                    # Digit count regex found nothing -- check for a
                    # spelled-out count word ("top five funds") instead.
                    word_n = extract_number_word(ql)
                    if word_n:
                        n = word_n
                if cat_text:
                    cat_text = re.sub(r"\bfunds?\b", "", cat_text).strip(" ?.!")
                    return "top_funds", {"category_text": cat_text, "n": n, "amc": amc}

        if any(kw in ql for kw in ["tell me about", "info on", "information about",
                                    "details of", "details on", "about the fund",
                                    "how is", "how's"]):
            for trigger in ["tell me about", "info on", "information about",
                             "details of", "details on", "about the fund", "how is", "how's"]:
                if trigger in ql:
                    idx = ql.index(trigger) + len(trigger)
                    # Fund lookups use the ORIGINAL (AMC-inclusive) text --
                    # the AMC name is usually part of the scheme name
                    # itself (e.g. "HDFC Flexi Cap Fund"), so it should NOT
                    # be stripped here the way it is for category queries.
                    idx_full = q.lower().index(trigger) + len(trigger)
                    return "fund_info", {"fund_text": q[idx_full:].strip(" ?.!")}

        # Explicit request to browse categories -> kick off the guided flow.
        if any(kw in ql for kw in ["show categories", "browse funds", "show funds",
                                    "which categories", "list categories",
                                    "top funds", "show me funds"]) and not self.match_sub_categories(q_wo_amc):
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
            best_sc, score = self.best_sub_category_match(q_wo_amc)
            if best_sc and score >= SUBCAT_MATCH_THRESHOLD:
                return "top_funds", {"category_text": q_wo_amc, "n": 10, "amc": amc}

        if not generic_question:
            # Fund-name lookups use the ORIGINAL text (AMC is typically
            # part of the scheme name, e.g. "HDFC Flexi Cap Fund").
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
            amc = params.get("amc")
            return self.format_top_funds(best_sc, n=params.get("n", 10), amc=amc)

        if intent == "fund_info":
            fund_text = params["fund_text"]
            candidates = self.match_funds_ranked(fund_text, n=6)
            if candidates.empty:
                return f"I couldn't find a fund matching '{fund_text}' in the dataset."
            if len(candidates) == 1:
                # Only one close match -- nothing ambiguous to choose
                # between, so show its profile directly.
                return self.format_fund_profile(candidates.iloc[0])
            # Multiple close matches (different AMCs' similarly-named
            # funds, Direct vs Regular plan, Growth vs IDCW, ...) -- let
            # the user pick rather than silently guessing for them. Same
            # tappable-options mechanism as the Asset Type / Sub Category
            # guided flow (see pending_options_payload() / app.py).
            self.pending = {
                "stage": "await_fund_choice",
                "options": candidates["Scheme Name"].tolist(),
            }
            return self._render_prompt(f"A few funds match \"{fund_text}\" — which one?")

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
