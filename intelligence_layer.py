import json
import streamlit as st
from groq import Groq
from data_layer import generate_insights


# ─────────────────────────────────────────
# GROQ CLIENT
# ─────────────────────────────────────────

def get_groq_client():
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


# ─────────────────────────────────────────
# BUILD CONTEXT SUMMARY FOR LLM
# ─────────────────────────────────────────

def build_context_summary(deals_df, orders_df, question, quality_issues):
    """
    Build a concise data summary to send to the LLM.
    We never send the full DataFrame — too large.
    Instead we send key stats + relevant filtered rows.
    """

    insights = generate_insights(deals_df, orders_df)

    # ── Detect question intent for smart filtering ──
    question_lower = question.lower()

    # Sector filter
    sector_filter = None
    for sector in ["mining", "powerline", "renewables", "railways", "construction", "others", "dsp"]:
        if sector in question_lower:
            sector_filter = sector.title()
            break

    # Status filter
    status_filter = None
    if any(w in question_lower for w in ["open", "active"]):
        status_filter = "Open"
    elif "won" in question_lower:
        status_filter = "Won"
    elif "dead" in question_lower:
        status_filter = "Dead"
    elif "hold" in question_lower:
        status_filter = "On Hold"

    # Probability filter
    prob_filter = None
    if "high" in question_lower and "probability" in question_lower:
        prob_filter = "High"
    elif "low" in question_lower and "probability" in question_lower:
        prob_filter = "Low"
    elif "medium" in question_lower and "probability" in question_lower:
        prob_filter = "Medium"

    # ── Filter deals if needed ──
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

    # ── Filter work orders if needed ──
    filtered_orders = orders_df.copy()
    if sector_filter and "sector" in filtered_orders.columns:
        filtered_orders = filtered_orders[
            filtered_orders["sector"].str.contains(sector_filter, case=False, na=False)
        ]

    # ── Build sample rows for context ──
    deal_samples = []
    for _, row in filtered_deals.head(10).iterrows():
        sample = {
            "name": row.get("deal_name", "Unknown"),
            "status": row.get("deal_status"),
            "sector": row.get("sector"),
            "value": f"₹{row['deal_value']:,.0f}" if row.get("deal_value") else "Not provided",
            "probability": row.get("closure_probability"),
            "close_date": str(row.get("close_date")) if row.get("close_date") else None,
            "tentative_close": str(row.get("tentative_close_date")) if row.get("tentative_close_date") else None,
            "stage": row.get("deal_stage"),
        }
        deal_samples.append(sample)

    order_samples = []
    for _, row in filtered_orders.head(8).iterrows():
        sample = {
            "name": row.get("deal_name", "Unknown"),
            "status": row.get("execution_status"),
            "sector": row.get("sector"),
            "contract_value": f"₹{row['amount_excl_gst']:,.0f}" if row.get("amount_excl_gst") else "Not provided",
            "collected": f"₹{row['collected_amount']:,.0f}" if row.get("collected_amount") else "Not provided",
            "receivable": f"₹{row['amount_receivable']:,.0f}" if row.get("amount_receivable") else "Not provided",
            "billing_status": row.get("billing_status"),
        }
        order_samples.append(sample)

    # ── Filtered stats ──
    filtered_stats = {}
    if len(filtered_deals) > 0:
        filtered_stats["matching_deals"] = len(filtered_deals)
        values = filtered_deals["deal_value"].dropna() if "deal_value" in filtered_deals.columns else []
        if len(values) > 0:
            filtered_stats["total_value"] = f"₹{values.sum():,.0f}"
            filtered_stats["avg_value"] = f"₹{values.mean():,.0f}"
            filtered_stats["deals_with_values"] = len(values)
            filtered_stats["deals_missing_values"] = len(filtered_deals) - len(values)

    if len(filtered_orders) > 0:
        filtered_stats["matching_orders"] = len(filtered_orders)
        collected = filtered_orders["collected_amount"].dropna() if "collected_amount" in filtered_orders.columns else []
        receivable = filtered_orders["amount_receivable"].dropna() if "amount_receivable" in filtered_orders.columns else []
        if len(collected) > 0:
            filtered_stats["total_collected"] = f"₹{collected.sum():,.0f}"
        if len(receivable) > 0:
            filtered_stats["total_receivable"] = f"₹{receivable.sum():,.0f}"

    # ── Assemble full context ──
    context = {
        "question": question,
        "filters_applied": filters_applied,
        "overall_summary": {
            "total_deals": insights.get("total_deals", 0),
            "deals_by_status": insights.get("deals_by_status", {}),
            "deals_by_sector": insights.get("deals_by_sector", {}),
            "deals_by_probability": insights.get("deals_by_probability", {}),
            "total_pipeline_value": f"₹{insights['total_pipeline_value']:,.0f}" if insights.get("total_pipeline_value") else "N/A",
            "deals_with_values": insights.get("deals_with_values", 0),
            "missing_deal_values": insights.get("missing_deal_values", 0),
            "missing_probability": insights.get("missing_probability", 0),
            "total_work_orders": insights.get("total_work_orders", 0),
            "orders_by_status": insights.get("orders_by_status", {}),
            "orders_by_sector": insights.get("orders_by_sector", {}),
            "total_collected": f"₹{insights['total_collected']:,.0f}" if insights.get("total_collected") else "N/A",
            "total_receivable": f"₹{insights['total_receivable']:,.0f}" if insights.get("total_receivable") else "N/A",
            "total_contract_value": f"₹{insights['total_contract_value']:,.0f}" if insights.get("total_contract_value") else "N/A",
        },
        "filtered_results": filtered_stats,
        "sample_deals": deal_samples,
        "sample_work_orders": order_samples,
        "data_quality_caveats": quality_issues[:15],
    }

    return json.dumps(context, indent=2, default=str)


# ─────────────────────────────────────────
# GENERATE ANSWER
# ─────────────────────────────────────────

def generate_answer(question, deals_df, orders_df, chat_history, quality_issues):
    """
    Use Groq Llama 3.3 70B to generate a conversational BI answer.
    Returns the answer string.
    """

    client = get_groq_client()
    context = build_context_summary(deals_df, orders_df, question, quality_issues)

    system_prompt = """You are an expert BI analyst for Skylark Drones, a drone survey company in India.
Your job is to answer founder-level business questions about deal pipeline and work orders.

RULES:
1. Always use ₹ for currency. Format large numbers as crores (e.g., ₹18.9 Cr) or lakhs (₹2.3 L).
2. Be conversational and direct — founders want quick insights, not essays.
3. Always mention data quality caveats that affect your answer (missing values, null fields).
4. When totals are based on partial data, say so clearly (e.g., "based on 9 of 23 deals with values").
5. Use specific numbers from the data provided — never make up figures.
6. If a question references previous conversation, use that context.
7. End with 1 relevant follow-up insight the founder might want to know.

CURRENCY FORMAT:
- Above 1 crore: use "X.X Cr" (e.g., ₹18.9 Cr)
- Below 1 crore: use "X.X L" (e.g., ₹45.2 L)
- Exact small amounts: use comma format (e.g., ₹4,28,190)"""

    user_prompt = f"""DATA CONTEXT:
{context}

PREVIOUS CONVERSATION:
{chat_history if chat_history else "This is the first question."}

FOUNDER'S QUESTION: {question}

Answer conversationally. Be specific with numbers. Note data quality issues where relevant."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=1000
    )

    return response.choices[0].message.content


# ─────────────────────────────────────────
# CREATE TRACE
# ─────────────────────────────────────────

def create_trace(trace_info, quality_issues_count, question):
    """
    Build a human-readable trace of all operations performed.
    Shows API calls, normalization steps, and LLM processing.
    """

    deals_count = trace_info.get("deals_count", 0)
    orders_count = trace_info.get("orders_count", 0)
    deals_fetch = trace_info.get("deals_fetch_time", 0)
    orders_fetch = trace_info.get("orders_fetch_time", 0)
    normalize_time = trace_info.get("normalize_time", 0)
    llm_time = trace_info.get("llm_time", 0)
    total_time = deals_fetch + orders_fetch + normalize_time + llm_time

    trace = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENT TRACE — Processing your query
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1: Live API Fetch (Monday.com)
  ├─ Board: Deals
  │   ├─ Endpoint: api.monday.com/v2 (GraphQL)
  │   ├─ Items fetched: {deals_count}
  │   └─ Time: {deals_fetch}s ✓
  └─ Board: Work Orders
      ├─ Endpoint: api.monday.com/v2 (GraphQL)
      ├─ Items fetched: {orders_count}
      └─ Time: {orders_fetch}s ✓

STEP 2: Data Normalization
  ├─ Removed duplicate header rows (Deal Status == 'Deal Status')
  ├─ Parsed all date fields to standard format
  ├─ Normalized sector names → Title Case
  ├─ Treated 0.0 financial values as missing (not zero)
  ├─ Fixed typo: 'BIlled' → 'Billed'
  ├─ Normalized execution status variants → 5 standard categories
  ├─ Data quality issues found: {quality_issues_count}
  └─ Time: {normalize_time}s ✓

STEP 3: Query Understanding
  ├─ Question: "{question[:60]}{'...' if len(question) > 60 else ''}"
  ├─ Detected filters: sector / status / probability keywords
  └─ Built context summary for LLM ✓

STEP 4: AI Response (Groq)
  ├─ Model: Llama 3.3 70B (llama-3.3-70b-versatile)
  ├─ Temperature: 0.3 (consistent, factual)
  ├─ Time: {llm_time}s ✓
  └─ Status: Success ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Processing Time: {round(total_time, 2)}s
Data freshness: Live (no cache)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    return trace