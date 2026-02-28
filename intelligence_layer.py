# intelligence_layer.py
# Thin orchestration layer — imports context_builder and prompt_engine.
# Calls Groq API with pre-built prompt.

import json
import streamlit as st
from groq import Groq

from context_builder import build_full_context
from prompt_engine import SYSTEM_PROMPT, build_user_prompt


@st.cache_resource
def get_groq_client():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


def generate_answer(question, deals_df, orders_df, chat_history, quality_summary):
    """
    Build context → build prompt → call Groq → return answer string.
    """
    client = get_groq_client()

    # Build structured context
    context_dict = build_full_context(
        deals_df=deals_df,
        orders_df=orders_df,
        question=question,
        quality_summary=quality_summary,
        chat_history=chat_history
    )

    context_json = json.dumps(context_dict, indent=2, default=str)
    user_prompt = build_user_prompt(context_json, question, chat_history)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=0.1,   # Very low — we want consistent factual answers
        max_tokens=1000
    )

    return response.choices[0].message.content


def create_trace(trace_info, quality_summary, question):
    """Build human-readable agent trace."""
    deals_count    = trace_info.get("deals_count", 0)
    orders_count   = trace_info.get("orders_count", 0)
    deals_fetch    = trace_info.get("deals_fetch_time", 0)
    orders_fetch   = trace_info.get("orders_fetch_time", 0)
    normalize_time = trace_info.get("normalize_time", 0)
    llm_time       = trace_info.get("llm_time", 0)
    total_time     = round(deals_fetch + orders_fetch + normalize_time + llm_time, 2)

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
  ├─ On Hold deals list resolved
  └─ Full structured JSON context sent to LLM ✓

STEP 4: Prompt Engine (prompt_engine.py)
  ├─ PTFC prompt: Person + Task + Format + Context
  ├─ 7 calculation rules injected (win rate, collection rate, etc.)
  ├─ Known facts hardcoded (On Hold sectors, best win rate, etc.)
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