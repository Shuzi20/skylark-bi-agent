# data_layer.py
import pandas as pd
import requests
import streamlit as st
from datetime import datetime
import time

MONDAY_API_URL = "https://api.monday.com/v2"

# ─────────────────────────────────────────
# REAL COLUMN IDs (fetched from API Playground)
# ─────────────────────────────────────────

# DEALS BOARD — board id: 5026905724
DEALS_COLUMNS = {
    "owner_code":            "text_mm10908h",
    "client_code":           "text_mm10vc4q",
    "deal_status":           "color_mm10njxv",
    "close_date":            "date_mm10ktqz",
    "closure_probability":   "color_mm102cah",
    "deal_value":            "numeric_mm10shmc",
    "tentative_close_date":  "date_mm102pqv",
    "deal_stage":            "color_mm10pgmy",
    "product_deal":          "color_mm10890d",
    "sector":                "dropdown_mm10nf8h",
    "created_date":          "date_mm10dg9p",
}

# WORK ORDERS BOARD — board id: 5026903340
WORK_ORDER_COLUMNS = {
    "customer_code":         "text_mm10hpnp",
    "serial_number":         "text_mm10paqa",
    "nature_of_work":        "text_mm10rfz2",
    "execution_status":      "color_mm10r6dj",
    "data_delivery_date":    "date_mm1048vj",
    "date_po_loi":           "date_mm10438k",
    "probable_start_date":   "date_mm105byk",
    "probable_end_date":     "date_mm10jwcq",
    "sector":                "color_mm10h01",
    "type_of_work":          "color_mm10b9qt",
    "last_invoice_date":     "date_mm10eny3",
    "latest_invoice_no":     "text_mm10xe85",
    "amount_excl_gst":       "numeric_mm10pcr6",
    "amount_incl_gst":       "numeric_mm10meea",
    "billed_excl_gst":       "numeric_mm10gmcg",
    "billed_incl_gst":       "numeric_mm10yszy",
    "collected_amount":      "numeric_mm109v1q",
    "amount_to_bill_excl":   "numeric_mm10f93v",
    "amount_to_bill_incl":   "numeric_mm10pq92",
    "amount_receivable":     "numeric_mm10eahs",
    "invoice_status":        "color_mm109qab",
    "expected_billing_month":"text_mm10cemb",
    "actual_billing_month":  "color_mm10a06p",
    "actual_collection_month":"text_mm10rxrt",
    "wo_status":             "color_mm10bph0",
    "collection_status":     "text_mm10kvds",
    "billing_status":        "color_mm10gb28",
}


# ─────────────────────────────────────────
# FETCH FROM MONDAY.COM (Live, no cache)
# ─────────────────────────────────────────

def fetch_board_items(board_id):
    """
    Fetch all items from a Monday.com board via GraphQL.
    Always fresh — no caching anywhere.
    """
    query = """
    query ($boardId: [ID!]!) {
      boards(ids: $boardId) {
        items_page(limit: 500) {
          items {
            id
            name
            column_values {
              id
              text
              value
            }
          }
        }
      }
    }
    """

    headers = {
        "Authorization": st.secrets["MONDAY_API_TOKEN"],
        "Content-Type": "application/json",
        "API-Version": "2024-01"
    }

    response = requests.post(
        MONDAY_API_URL,
        json={"query": query, "variables": {"boardId": [str(board_id)]}},
        headers=headers,
        timeout=15
    )

    if response.status_code != 200:
        raise Exception(f"Monday.com API error {response.status_code}: {response.text}")

    data = response.json()
    if "errors" in data:
        raise Exception(f"GraphQL error: {data['errors']}")

    items = data["data"]["boards"][0]["items_page"]["items"]

    # Warn if we might have hit the 500 limit
    if len(items) == 500:
        print("WARNING: Fetched exactly 500 items — board may have more records.")

    return data


def fetch_deals_live():
    """Fetch Deals board. Always fresh."""
    return fetch_board_items(st.secrets["MONDAY_DEALS_BOARD_ID"])


def fetch_work_orders_live():
    """Fetch Work Orders board. Always fresh."""
    return fetch_board_items(st.secrets["MONDAY_WORK_ORDERS_BOARD_ID"])


# ─────────────────────────────────────────
# NORMALIZE DEALS
# ─────────────────────────────────────────

def normalize_deals(raw_response):
    """
    Parse raw Monday.com API response into a clean Deals DataFrame.
    Uses REAL column IDs from DEALS_COLUMNS mapping.
    Returns: (DataFrame, quality_issues list, quality_summary dict)
    """
    quality_issues = []
    deals = []

    # Counters for summary
    missing_value_count = 0
    missing_prob_count = 0
    missing_date_count = 0
    skipped_header_rows = 0

    try:
        items = raw_response["data"]["boards"][0]["items_page"]["items"]
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected API response structure: {e}")

    for item in items:
        # Build lookup: column_id → text value
        cols = {cv["id"]: (cv.get("text") or "") for cv in item["column_values"]}

        # ── Filter duplicate header rows ──
        status_raw = cols.get(DEALS_COLUMNS["deal_status"], "").strip()
        if status_raw == "Deal Status":
            skipped_header_rows += 1
            continue

        deal = {
            "id":                   item["id"],
            "deal_name":            item.get("name", "").strip(),
            "owner_code":           cols.get(DEALS_COLUMNS["owner_code"], "").strip() or None,
            "client_code":          cols.get(DEALS_COLUMNS["client_code"], "").strip() or None,
            "deal_status":          None,
            "close_date":           None,
            "closure_probability":  None,
            "deal_value":           None,
            "tentative_close_date": None,
            "deal_stage":           cols.get(DEALS_COLUMNS["deal_stage"], "").strip() or None,
            "product_deal":         cols.get(DEALS_COLUMNS["product_deal"], "").strip() or None,
            "sector":               None,
            "created_date":         None,
        }

        # ── Deal Status ──
        if status_raw in ["Won", "Dead", "Open", "On Hold"]:
            deal["deal_status"] = status_raw
        elif status_raw:
            quality_issues.append(f"Deal '{deal['deal_name']}': Unknown status '{status_raw}'")
            deal["deal_status"] = status_raw

        # ── Closure Probability ──
        prob_raw = cols.get(DEALS_COLUMNS["closure_probability"], "").strip()
        if prob_raw in ["High", "Medium", "Low"]:
            deal["closure_probability"] = prob_raw
        else:
            missing_prob_count += 1

        # ── Deal Value ──
        val_raw = cols.get(DEALS_COLUMNS["deal_value"], "")
        deal["deal_value"] = _parse_number(val_raw)
        if deal["deal_value"] is None:
            missing_value_count += 1

        # ── Dates ──
        close_raw = cols.get(DEALS_COLUMNS["close_date"], "")
        tentative_raw = cols.get(DEALS_COLUMNS["tentative_close_date"], "")
        deal["close_date"] = _parse_date(close_raw)
        deal["tentative_close_date"] = _parse_date(tentative_raw)

        if not deal["close_date"] and not deal["tentative_close_date"]:
            missing_date_count += 1

        # ── Sector ──
        sector_raw = cols.get(DEALS_COLUMNS["sector"], "").strip()
        deal["sector"] = sector_raw.title() if sector_raw else None

        # ── Created Date ──
        deal["created_date"] = _parse_date(cols.get(DEALS_COLUMNS["created_date"], ""))

        deals.append(deal)

    df = pd.DataFrame(deals) if deals else pd.DataFrame()

    # Build quality summary (send COUNTS to LLM, not 400 individual rows)
    quality_summary = {
        "total_deals": len(deals),
        "skipped_header_rows": skipped_header_rows,
        "missing_deal_value": missing_value_count,
        "missing_closure_probability": missing_prob_count,
        "missing_close_dates": missing_date_count,
        "pct_missing_value": f"{round(missing_value_count/max(len(deals),1)*100)}%",
        "pct_missing_probability": f"{round(missing_prob_count/max(len(deals),1)*100)}%",
    }

    return df, quality_issues, quality_summary


# ─────────────────────────────────────────
# NORMALIZE WORK ORDERS
# ─────────────────────────────────────────

def normalize_work_orders(raw_response):
    """
    Parse raw Monday.com API response into a clean Work Orders DataFrame.
    Uses REAL column IDs from WORK_ORDER_COLUMNS mapping.
    Treats 0.0 as missing in ALL financial columns.
    Returns: (DataFrame, quality_issues list, quality_summary dict)
    """
    quality_issues = []
    orders = []

    missing_financial_count = 0
    billing_typo_fixed = 0

    try:
        items = raw_response["data"]["boards"][0]["items_page"]["items"]
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected API response structure: {e}")

    for item in items:
        cols = {cv["id"]: (cv.get("text") or "") for cv in item["column_values"]}

        order = {
            "id":                    item["id"],
            "deal_name":             item.get("name", "").strip(),
            "customer_code":         cols.get(WORK_ORDER_COLUMNS["customer_code"], "").strip() or None,
            "serial_number":         cols.get(WORK_ORDER_COLUMNS["serial_number"], "").strip() or None,
            "nature_of_work":        cols.get(WORK_ORDER_COLUMNS["nature_of_work"], "").strip() or None,
            "execution_status":      None,
            "sector":                None,
            "type_of_work":          cols.get(WORK_ORDER_COLUMNS["type_of_work"], "").strip() or None,
            "amount_excl_gst":       None,
            "amount_incl_gst":       None,
            "billed_excl_gst":       None,
            "billed_incl_gst":       None,
            "collected_amount":      None,
            "amount_to_bill_excl":   None,
            "amount_to_bill_incl":   None,
            "amount_receivable":     None,
            "billing_status":        None,
            "wo_status":             cols.get(WORK_ORDER_COLUMNS["wo_status"], "").strip() or None,
            "invoice_status":        cols.get(WORK_ORDER_COLUMNS["invoice_status"], "").strip() or None,
            "probable_start_date":   None,
            "probable_end_date":     None,
            "data_delivery_date":    None,
            "last_invoice_date":     None,
            "actual_collection_month": cols.get(WORK_ORDER_COLUMNS["actual_collection_month"], "").strip() or None,
            "expected_billing_month":  cols.get(WORK_ORDER_COLUMNS["expected_billing_month"], "").strip() or None,
        }

        # ── Execution Status (normalize 8+ variants) ──
        exec_raw = cols.get(WORK_ORDER_COLUMNS["execution_status"], "").strip()
        order["execution_status"] = _normalize_execution_status(exec_raw)

        # ── Sector ──
        sector_raw = cols.get(WORK_ORDER_COLUMNS["sector"], "").strip()
        order["sector"] = sector_raw.title() if sector_raw else None

        # ── Financial fields — treat 0.0 as missing ──
        fin_fields = [
            ("amount_excl_gst",     "amount_excl_gst"),
            ("amount_incl_gst",     "amount_incl_gst"),
            ("billed_excl_gst",     "billed_excl_gst"),
            ("billed_incl_gst",     "billed_incl_gst"),
            ("collected_amount",    "collected_amount"),
            ("amount_to_bill_excl", "amount_to_bill_excl"),
            ("amount_to_bill_incl", "amount_to_bill_incl"),
            ("amount_receivable",   "amount_receivable"),
        ]
        for order_key, col_key in fin_fields:
            raw_val = cols.get(WORK_ORDER_COLUMNS[col_key], "")
            parsed = _parse_number(raw_val)
            if parsed is not None and parsed > 0:
                order[order_key] = parsed
            elif raw_val:
                missing_financial_count += 1

        # ── Billing Status — fix typo 'BIlled' → 'Billed' ──
        billing_raw = cols.get(WORK_ORDER_COLUMNS["billing_status"], "").strip()
        if "BIlled" in billing_raw:
            billing_raw = billing_raw.replace("BIlled", "Billed")
            billing_typo_fixed += 1
        order["billing_status"] = billing_raw or None

        # ── Dates ──
        order["probable_start_date"] = _parse_date(cols.get(WORK_ORDER_COLUMNS["probable_start_date"], ""))
        order["probable_end_date"]   = _parse_date(cols.get(WORK_ORDER_COLUMNS["probable_end_date"], ""))
        order["data_delivery_date"]  = _parse_date(cols.get(WORK_ORDER_COLUMNS["data_delivery_date"], ""))
        order["last_invoice_date"]   = _parse_date(cols.get(WORK_ORDER_COLUMNS["last_invoice_date"], ""))

        orders.append(order)

    df = pd.DataFrame(orders) if orders else pd.DataFrame()

    quality_summary = {
        "total_orders": len(orders),
        "missing_financial_values": missing_financial_count,
        "billing_typos_fixed": billing_typo_fixed,
    }

    return df, quality_issues, quality_summary


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def fetch_and_normalize_all():
    """
    Fetch both boards fresh, normalize, return clean DataFrames.
    Returns: (deals_df, orders_df, quality_summary_dict, trace_info_dict)
    """
    trace_info = {}

    # Fetch Deals
    t0 = time.time()
    raw_deals = fetch_deals_live()
    trace_info["deals_fetch_time"] = round(time.time() - t0, 2)

    # Fetch Work Orders
    t0 = time.time()
    raw_orders = fetch_work_orders_live()
    trace_info["orders_fetch_time"] = round(time.time() - t0, 2)

    # Normalize
    t0 = time.time()
    deals_df, deals_issues, deals_summary = normalize_deals(raw_deals)
    orders_df, orders_issues, orders_summary = normalize_work_orders(raw_orders)
    trace_info["normalize_time"] = round(time.time() - t0, 2)

    trace_info["deals_count"] = len(deals_df)
    trace_info["orders_count"] = len(orders_df)

    # Merge quality summaries
    quality_summary = {**deals_summary, **orders_summary}
    quality_summary["all_issues"] = deals_issues + orders_issues

    return deals_df, orders_df, quality_summary, trace_info


# ─────────────────────────────────────────
# INSIGHTS GENERATOR
# ─────────────────────────────────────────

def generate_insights(deals_df, orders_df):
    """Calculate key business metrics. Returns dict for LLM context."""
    insights = {}

    # Deals
    insights["total_deals"] = len(deals_df)

    if "deal_status" in deals_df.columns:
        insights["deals_by_status"] = deals_df["deal_status"].value_counts().to_dict()

    if "sector" in deals_df.columns:
        insights["deals_by_sector"] = (
            deals_df["sector"].dropna().value_counts().to_dict()
        )

    if "closure_probability" in deals_df.columns:
        insights["deals_by_probability"] = (
            deals_df["closure_probability"].dropna().value_counts().to_dict()
        )

    if "deal_value" in deals_df.columns:
        valid = deals_df["deal_value"].dropna()
        insights["deals_with_values"] = len(valid)
        insights["missing_deal_values"] = len(deals_df) - len(valid)
        if len(valid) > 0:
            insights["total_pipeline_value"] = float(valid.sum())
            insights["avg_deal_value"] = float(valid.mean())

    # Work Orders
    insights["total_work_orders"] = len(orders_df)

    if "execution_status" in orders_df.columns:
        insights["orders_by_status"] = (
            orders_df["execution_status"].dropna().value_counts().to_dict()
        )

    if "sector" in orders_df.columns:
        insights["orders_by_sector"] = (
            orders_df["sector"].dropna().value_counts().to_dict()
        )

    for field in ["collected_amount", "amount_receivable", "amount_excl_gst"]:
        if field in orders_df.columns:
            valid = orders_df[field].dropna()
            insights[f"total_{field}"] = float(valid.sum()) if len(valid) > 0 else 0

    return insights


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def _parse_number(val):
    """Parse float. Returns None if empty, unparseable, or zero (treated as missing)."""
    if val is None or str(val).strip() in ["", "nan", "None"]:
        return None
    try:
        num = float(str(val).replace(",", "").strip())
        return num if num != 0.0 else None  # 0.0 = missing data in this dataset
    except (ValueError, TypeError):
        return None


def _parse_date(val):
    """Parse various date formats. Returns date object or None."""
    if not val or str(val).strip() in ["", "nan", "None", "NaT"]:
        return None
    val = str(val).strip()[:10]  # Take first 10 chars (handles datetime strings)
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y"]:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_execution_status(raw):
    """Normalize 8+ execution status variants to 5 standard categories."""
    if not raw:
        return None
    raw = raw.strip()
    if any(x in raw for x in ["Completed", "Executed"]):
        return "Completed"
    if "Not Started" in raw:
        return "Not Started"
    if any(x in raw for x in ["Ongoing", "In Progress"]):
        return "Ongoing"
    if "Partial" in raw:
        return "Partial Completed"
    if any(x in raw for x in ["Pause", "struck", "Hold"]):
        return "Paused"
    if "Details pending" in raw:
        return "Details Pending"
    return raw  # Keep unknown as-is