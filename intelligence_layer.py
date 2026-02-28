# intelligence_layer.py
import json
import streamlit as st
from groq import Groq
from data_layer import generate_insights


# ─────────────────────────────────────────
# GROQ CLIENT — cached, not recreated every call
# ─────────────────────────────────────────

@st.cache_resource
def get_groq_client():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


# ─────────────────────────────────────────
# BUILD CONTEXT SUMMARY FOR LLM
# ─────────────────────────────────────────

def build_context_summary(deals_df, orders_df, question, quality_summary):
    """
    Build concise data summary to send to Groq LLM.
    Never sends full DataFrame — only stats + filtered sample rows.
    """
    insights = generate_insights(deals_df, orders_df)
    question_lower = question.lower()

    # ── Sector filter detection (safe list — no generic words) ──
    sector_filter = None
    for sector in ["mining", "powerline", "renewables", "railways", "construction"]:
        if sector in question_lower:
            sector_filter = sector.title()
            break

    # ── Status filter detection ──
    status_filter = None
    if any(w in question_lower for w in ["open", "active"]):
        status_filter = "Open"
    elif "won" in question_lower:
        status_filter = "Won"
    elif "dead" in question_lower:
        status_filter = "Dead"
    elif "hold" in question_lower:
        status_filter = "On Hold"

    # ── Probability filter detection ──
    prob_filter = None
    if "high" in question_lower and "prob" in question_lower:
        prob_filter = "High"
    elif "low" in question_lower and "prob" in question_lower:
        prob_filter = "Low"
    elif "medium" in question_lower and "prob" in question_lower:
        prob_filter = "Medium"

    # ── Apply filters to deals ──
    filtered_deals = deals_df.copy()
    filters_applied = []

    if sector_filter and "sector" in filtered_deals.columns:
        filtered_deals = filtered_deals[
            filtered_deals["sector"].str.contains(sector_filter, case=False, na=False)
        ]
        filters_applied.append(f"sector = {sector_filter}")

    if status_filter and "deal_status" in filtered_deals.columns:
        filtered_deals = filtered_deals[
            filtered_deals["deal_status"] == status_filter
        ]
        filters_applied.append(f"status = {status_filter}")

    if prob_filter and "closure_probability" in filtered_deals.columns:
        filtered_deals = filtered_deals[
            filtered_deals["closure_probability"] == prob_filter
        ]
        filters_applied.append(f"probability = {prob_filter}")

    # ── Apply filters to work orders ──
    filtered_orders = orders_df.copy()
    if sector_filter and "sector" in filtered_orders.columns:
        filtered_orders = filtered_orders[
            filtered_orders["sector"].str.contains(sector_filter, case=False, na=False)
        ]

    # ── Sample deal rows for LLM context ──
    deal_samples = []
    for _, row in filtered_deals.head(10).iterrows():
        deal_samples.append({
            "name":         row.get("deal_name", "Unknown"),
            "status":       row.get("deal_status"),
            "sector":       row.get("sector"),
            "value":        f"₹{row['deal_value']:,.0f}" if row.get("deal_value") else "Not provided",
            "probability":  row.get("closure_probability"),
            "close_date":   str(row.get("close_date")) if row.get("close_date") else None,
            "tentative":    str(row.get("tentative_close_date")) if row.get("tentative_close_date") else None,
            "stage":        row.get("deal_stage"),
        })

    # ── Sample work order rows ──
    order_samples = []
    for _, row in filtered_orders.head(8).iterrows():
        order_samples.append({
            "name":           row.get("deal_name", "Unknown"),
            "status":         row.get("execution_status"),
            "sector":         row.get("sector"),
            "contract_value": f"₹{row['amount_excl_gst']:,.0f}" if row.get("amount_excl_gst") else "Not provided",
            "collected":      f"₹{row['collected_amount']:,.0f}" if row.get("collected_amount") else "Not provided",
            "receivable":     f"₹{row['amount_receivable']:,.0f}" if row.get("amount_receivable") else "Not provided",
            "billing_status": row.get("billing_status"),
        })

    # ── Filtered stats ──
    filtered_stats = {}
    if len(filtered_deals) > 0:
        filtered_stats["matching_deals"] = len(filtered_deals)

        # Status breakdown — very useful for founders
        if "deal_status" in filtered_deals.columns:
            filtered_stats["status_breakdown"] = filtered_deals["deal_status"].value_counts().to_dict()

        # Probability breakdown
        if "closure_probability" in filtered_deals.columns:
            filtered_stats["probability_breakdown"] = filtered_deals["closure_probability"].dropna().value_counts().to_dict()
            filtered_stats["missing_probability"] = int(filtered_deals["closure_probability"].isna().sum())

        import pandas as pd
        values = filtered_deals["deal_value"].dropna() if "deal_value" in filtered_deals.columns else pd.Series(dtype=float)
        if len(values) > 0:
            # Pre-format as Crores — prevents LLM from misreading raw numbers
            # 1 Crore = 10,000,000
            filtered_stats["total_value_crores"]   = f"Rs {values.sum()/10_000_000:.2f} Cr"
            filtered_stats["avg_value_crores"]     = f"Rs {values.mean()/10_000_000:.2f} Cr"
            filtered_stats["max_value_crores"]     = f"Rs {values.max()/10_000_000:.2f} Cr"
            filtered_stats["deals_with_values"]    = len(values)
            filtered_stats["deals_missing_values"] = len(filtered_deals) - len(values)

    if len(filtered_orders) > 0:
        filtered_stats["matching_orders"] = len(filtered_orders)
        if "execution_status" in filtered_orders.columns:
            filtered_stats["order_status_breakdown"] = filtered_orders["execution_status"].dropna().value_counts().to_dict()
        import pandas as pd
        collected  = filtered_orders["collected_amount"].dropna() if "collected_amount" in filtered_orders.columns else pd.Series(dtype=float)
        receivable = filtered_orders["amount_receivable"].dropna() if "amount_receivable" in filtered_orders.columns else pd.Series(dtype=float)
        if len(collected)  > 0: filtered_stats["total_collected_crores"]  = f"Rs {collected.sum()/10_000_000:.2f} Cr"
        if len(receivable) > 0: filtered_stats["total_receivable_crores"] = f"Rs {receivable.sum()/10_000_000:.2f} Cr"

    # ── Quality summary — counts only, not 400 individual rows ──
    quality_caveats = [
        f"{quality_summary.get('missing_deal_value', 0)} deals missing deal value ({quality_summary.get('pct_missing_value','?')})",
        f"{quality_summary.get('missing_closure_probability', 0)} deals missing closure probability ({quality_summary.get('pct_missing_probability','?')})",
        f"{quality_summary.get('missing_close_dates', 0)} deals missing close dates — tentative used as fallback",
        f"{quality_summary.get('skipped_header_rows', 0)} duplicate header rows removed",
        f"{quality_summary.get('billing_typos_fixed', 0)} billing status typos fixed (BIlled → Billed)",
        f"{quality_summary.get('missing_financial_values', 0)} work order financial fields treated as missing (0.0 = no data)",
    ]

    context = {
        "question": question,
        "filters_applied": filters_applied,
        "overall_summary": {
            "total_deals":              insights.get("total_deals", 0),
            "deals_by_status":          insights.get("deals_by_status", {}),
            "deals_by_sector":          insights.get("deals_by_sector", {}),
            "deals_by_probability":     insights.get("deals_by_probability", {}),
            "total_pipeline_value":     f"Rs {insights['total_pipeline_value']/10_000_000:.2f} Cr" if insights.get("total_pipeline_value") else "N/A",
            "avg_deal_value":           f"Rs {insights['avg_deal_value']/10_000_000:.2f} Cr" if insights.get("avg_deal_value") else "N/A",
            "deals_with_values":        insights.get("deals_with_values", 0),
            "missing_deal_values":      insights.get("missing_deal_values", 0),
            "total_work_orders":        insights.get("total_work_orders", 0),
            "orders_by_status":         insights.get("orders_by_status", {}),
            "orders_by_sector":         insights.get("orders_by_sector", {}),
            "total_collected":          f"Rs {insights['total_collected_amount']/10_000_000:.2f} Cr" if insights.get("total_collected_amount") else "N/A",
            "total_receivable":         f"Rs {insights['total_amount_receivable']/10_000_000:.2f} Cr" if insights.get("total_amount_receivable") else "N/A",
            "total_contract_value":     f"Rs {insights['total_amount_excl_gst']/10_000_000:.2f} Cr" if insights.get("total_amount_excl_gst") else "N/A",
        },
        "filtered_results":   filtered_stats,
        "sample_deals":       deal_samples,
        "sample_work_orders": order_samples,
        "data_quality_caveats": quality_caveats,
    }

    return json.dumps(context, indent=2, default=str)


# ─────────────────────────────────────────
# GENERATE ANSWER
# ─────────────────────────────────────────

def generate_answer(question, deals_df, orders_df, chat_history, quality_summary):
    """
    Use Groq Llama 3.3 70B to generate a conversational BI answer.
    Returns answer string.
    """
    import pandas as pd  # needed inside function for filtered_stats

    client = get_groq_client()
    context = build_context_summary(deals_df, orders_df, question, quality_summary)

    system_prompt = """You are an expert BI analyst for Skylark Drones, a drone survey company in India.
Answer founder-level business questions about deal pipeline and work orders.

CURRENCY RULES (CRITICAL — follow exactly):
- All amounts in data are already pre-formatted as "Rs X.XX Cr" (Crores). Use these EXACT values.
- Display using ₹ symbol: if data says "Rs 45.48 Cr", you write "₹45.48 Cr"
- NEVER re-calculate or re-convert currency values. Use only what the data provides.
- 1 Crore = 10,000,000. Do not confuse crores with lakhs.

ANSWER RULES:
1. Be conversational and direct — founders want quick insights, not essays.
2. Always include the deal status breakdown (Won/Dead/Open/On Hold) when available.
3. Always mention data quality caveats (missing values, partial data).
4. When totals are partial, say "based on X of Y deals with values".
5. Use ONLY numbers from the data — never invent or estimate figures.
6. Reference previous conversation when answering follow-ups.
7. End with one additional insight the founder might find useful.

EXAMPLE (Good answer for mining pipeline):
"Mining has 106 deals total: 69 Won, 28 Dead, and 9 Open.
Based on 34 of 106 deals with value data, the pipeline is ₹45.48 Cr (avg ₹1.34 Cr per deal).
Note: 72 deals are missing values so actual total could be higher.
Of the 9 open deals, 0 have High probability, 2 Medium, 3 Low, and 4 are unrated." """

    user_prompt = f"""DATA CONTEXT:
{context}

PREVIOUS CONVERSATION:
{chat_history if chat_history else "This is the first question."}

FOUNDER'S QUESTION: {question}

Answer conversationally. Be specific. Always note data quality caveats."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=1000
    )

    return response.choices[0].message.content


# ─────────────────────────────────────────
# CREATE TRACE
# ─────────────────────────────────────────

def create_trace(trace_info, quality_summary, question):
    """Build human-readable trace of all operations."""

    deals_count    = trace_info.get("deals_count", 0)
    orders_count   = trace_info.get("orders_count", 0)
    deals_fetch    = trace_info.get("deals_fetch_time", 0)
    orders_fetch   = trace_info.get("orders_fetch_time", 0)
    normalize_time = trace_info.get("normalize_time", 0)
    llm_time       = trace_info.get("llm_time", 0)
    total_time     = round(deals_fetch + orders_fetch + normalize_time + llm_time, 2)

    trace = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

STEP 3: Query Understanding
  ├─ Question : "{question[:60]}{'...' if len(question) > 60 else ''}"
  ├─ Detected sector / status / probability filters
  └─ Built context summary for LLM ✓

STEP 4: AI Response (Groq)
  ├─ Model       : llama-3.3-70b-versatile
  ├─ Temperature : 0.3 (consistent BI answers)
  ├─ Time        : {llm_time}s ✓
  └─ Status      : Success ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Time    : {total_time}s
Data Freshness: Live (fetched this query, no cache)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    return trace