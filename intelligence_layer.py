# intelligence_layer.py
# Thin orchestration layer — imports context_builder and prompt_engine.
# Calls Groq API with pre-built prompt.
#
# Updates:
# [1] active_filters param added to generate_answer — passed from app.py session state
# [2] extract_filters_from_answer() — parses LLM answer to detect new filters for next turn

import json
import re
import streamlit as st
from groq import Groq

from context_builder import build_full_context
from prompt_engine import SYSTEM_PROMPT, build_user_prompt


@st.cache_resource
def get_groq_client():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


# ─────────────────────────────────────────
# FILTER EXTRACTION — detects active filters from conversation
# ─────────────────────────────────────────

# Sector group mappings — mirrors LAYER 0 in prompt
SECTOR_GROUPS = {
    "energy": ["Renewables", "Powerline"],
    "energy sector": ["Renewables", "Powerline"],
    "renewable energy": ["Renewables"],
    "renewables": ["Renewables"],
    "solar": ["Renewables"],
    "powerline": ["Powerline"],
    "transmission": ["Powerline"],
    "mining": ["Mining"],
    "railways": ["Railways"],
    "construction": ["Construction"],
    "infrastructure": ["Railways", "Construction", "Powerline"],
    "core sectors": ["Mining", "Renewables", "Railways"],
    "dsp": ["Dsp"],
    "aviation": ["Aviation"],
    "manufacturing": ["Manufacturing"],
    "others": ["Others"],
    "tender": ["Tender"],
    "security": ["Security And Surveillance"],
}


def extract_new_filters(question: str, existing_filters: list) -> list:
    """
    Detect filter changes from the current question.
    Returns updated filter list.
    Handles:
    - "exclude X" → add exclusion filter
    - "only X" / "focus on X" → add inclusion filter
    - "above/below X" → add value threshold filter
    - "this quarter" / "last quarter" → add time filter
    - "remove the X filter" / "include X back" → remove filter
    """
    q = question.lower().strip()
    filters = list(existing_filters)

    # ── EXCLUSION: "exclude energy", "without mining" ──
    excl_match = re.search(
        r"(?:exclude|without|remove|not including|ignoring)\s+(energy sector|energy|mining|railways|renewables|powerline|infrastructure|construction|dsp|aviation|manufacturing|tender|security|core sectors)",
        q
    )
    if excl_match:
        group = excl_match.group(1).strip()
        sectors = SECTOR_GROUPS.get(group, [group.title()])
        filter_str = f"exclude_sectors:{','.join(sectors)}"
        # Remove conflicting include filter for same sectors
        filters = [f for f in filters if not f.startswith("include_only_sectors:")]
        if filter_str not in filters:
            filters.append(filter_str)

    # ── INCLUSION: "only mining", "focus on renewables" ──
    incl_match = re.search(
        r"(?:only|just|focus on|show only|limit to)\s+(energy sector|energy|mining|railways|renewables|powerline|infrastructure|construction|dsp|aviation|manufacturing|tender|core sectors)",
        q
    )
    if incl_match:
        group = incl_match.group(1).strip()
        sectors = SECTOR_GROUPS.get(group, [group.title()])
        filter_str = f"include_only_sectors:{','.join(sectors)}"
        filters = [f for f in filters if not f.startswith("exclude_sectors:")]
        if filter_str not in filters:
            filters.append(filter_str)

    # ── VALUE THRESHOLD: "above 50k", "deals over 1 crore" ──
    thresh_match = re.search(
        r"(?:above|over|more than|greater than|below|under|less than)\s+(?:rs\.?\s*)?(\d+(?:\.\d+)?)\s*(k|l|lakh|cr|crore|crores)?",
        q
    )
    if thresh_match:
        amount = float(thresh_match.group(1))
        unit = (thresh_match.group(2) or "").lower()
        direction = "above" if re.search(r"above|over|more than|greater than", q) else "below"
        if unit in ("k",):
            amount *= 1000
        elif unit in ("l", "lakh"):
            amount *= 100_000
        elif unit in ("cr", "crore", "crores"):
            amount *= 10_000_000
        # Remove old threshold
        filters = [f for f in filters if not f.startswith("value_threshold:")]
        filters.append(f"value_threshold:{direction}:{int(amount)}")

    # ── TIME WINDOW ──
    if re.search(r"\blast quarter\b|\bprevious quarter\b|\blast 3 months\b", q):
        filters = [f for f in filters if not f.startswith("time_window:")]
        filters.append("time_window:last_quarter")
    elif re.search(r"\bthis quarter\b|\bcurrent quarter\b", q):
        filters = [f for f in filters if not f.startswith("time_window:")]
        filters.append("time_window:this_quarter")

    # ── REMOVAL: "remove that filter", "include energy back", "reset" ──
    if re.search(r"\breset\b|\bstart over\b|\bno filters\b|\bclear filters\b", q):
        filters = []
    elif re.search(r"(?:include|add back|bring back)\s+(energy|mining|railways|renewables|powerline)", q):
        bring_back = re.search(r"(?:include|add back|bring back)\s+(\w+)", q).group(1)
        sectors = SECTOR_GROUPS.get(bring_back, [bring_back.title()])
        # Remove exclusion of these sectors
        filters = [
            f for f in filters
            if not (f.startswith("exclude_sectors:") and any(s in f for s in sectors))
        ]

    return filters


def format_filters_for_display(filters: list) -> list:
    """Convert internal filter strings to human-readable labels."""
    labels = []
    for f in filters:
        if f.startswith("exclude_sectors:"):
            sectors = f.replace("exclude_sectors:", "").split(",")
            labels.append(f"Excluding sectors: {', '.join(sectors)}")
        elif f.startswith("include_only_sectors:"):
            sectors = f.replace("include_only_sectors:", "").split(",")
            labels.append(f"Only sectors: {', '.join(sectors)}")
        elif f.startswith("value_threshold:"):
            parts = f.split(":")
            labels.append(f"Deal value {parts[1]} Rs {int(parts[2]):,}")
        elif f.startswith("time_window:"):
            labels.append(f"Time window: {f.replace('time_window:', '').replace('_', ' ')}")
        else:
            labels.append(f)
    return labels


def generate_answer(question, deals_df, orders_df, chat_history, quality_summary, active_filters=None):
    """
    Build context → build prompt → call Groq → return answer string.
    active_filters: list of filter strings from session state
    """
    client = get_groq_client()
    active_filters = active_filters or []

    # Human-readable filter labels for LLM
    filter_labels = format_filters_for_display(active_filters)

    context_dict = build_full_context(
        deals_df=deals_df,
        orders_df=orders_df,
        question=question,
        quality_summary=quality_summary,
        chat_history=chat_history,
        active_filters=filter_labels
    )

    context_json = json.dumps(context_dict, default=str)
    user_prompt = build_user_prompt(context_json, question, chat_history, active_filters=filter_labels)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=1000
    )

    return response.choices[0].message.content


def create_trace(trace_info, quality_summary, question, active_filters=None):
    """Build human-readable agent trace."""
    deals_count    = trace_info.get("deals_count", 0)
    orders_count   = trace_info.get("orders_count", 0)
    deals_fetch    = trace_info.get("deals_fetch_time", 0)
    orders_fetch   = trace_info.get("orders_fetch_time", 0)
    normalize_time = trace_info.get("normalize_time", 0)
    llm_time       = trace_info.get("llm_time", 0)
    total_time     = round(deals_fetch + orders_fetch + normalize_time + llm_time, 2)

    filter_labels = format_filters_for_display(active_filters or [])
    filter_lines = "\n".join(f"  │   ├─ {f}" for f in filter_labels) if filter_labels else "  │   └─ None (full dataset)"

    return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENT TRACE — Processing Query
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1: Live API Fetch (Monday.com — no cache)
  ├─ Deals Board
  │   ├─ Endpoint : api.monday.com/v2 (GraphQL)
  │   ├─ Board ID : {st.secrets.get("MONDAY_DEALS_BOARD_ID", "?")}
  │   ├─ Items    : {deals_count}
  │   └─ Time     : {deals_fetch}s ✓
  └─ Work Orders Board
      ├─ Endpoint : api.monday.com/v2 (GraphQL)
      ├─ Board ID : {st.secrets.get("MONDAY_WORK_ORDERS_BOARD_ID", "?")}
      ├─ Items    : {orders_count}
      └─ Time     : {orders_fetch}s ✓

STEP 2: Data Normalization
  ├─ Removed {quality_summary.get('skipped_header_rows', 0)} duplicate header rows
  ├─ Parsed all date fields to standard format
  ├─ Sector names normalized → Title Case
  ├─ Financial 0.0 values → treated as missing
  ├─ Fixed {quality_summary.get('billing_typos_fixed', 0)} billing typos (BIlled → Billed)
  ├─ Execution status → 5 standard categories
  ├─ Data quality issues:
  │   ├─ Missing deal values    : {quality_summary.get('missing_deal_value', 0)} ({quality_summary.get('pct_missing_value','?')})
  │   ├─ Missing probability    : {quality_summary.get('missing_closure_probability', 0)} ({quality_summary.get('pct_missing_probability','?')})
  │   └─ Missing close dates    : {quality_summary.get('missing_close_dates', 0)} deals
  └─ Time: {normalize_time}s ✓

STEP 3: Context Building (context_builder.py)
  ├─ Pre-computed sector-wise deal stats (win rates, probabilities, values)
  ├─ Pre-computed work order financials per sector
  ├─ Win rate ranking built (won/closed formula)
  ├─ Quarterly pipeline computed (4 quarters)
  ├─ Value distribution thresholds computed
  ├─ Active session filters:
{filter_lines}
  └─ Full structured JSON context sent to LLM ✓

STEP 4: Prompt Engine (prompt_engine.py)
  ├─ 5-layer prompt: Domain | Math | Null Safety | Format | Filter Memory
  ├─ Active filters injected into SESSION CONTEXT block
  ├─ Sector group mappings loaded (energy=Renewables+Powerline)
  └─ User prompt assembled ✓

STEP 5: AI Response (Groq)
  ├─ Model       : llama-3.3-70b-versatile
  ├─ Temperature : 0.1 (highly consistent, factual)
  ├─ Time        : {llm_time}s ✓
  └─ Status      : Success ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Time    : {total_time}s
Data Freshness: Live (fetched this query, no cache)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""