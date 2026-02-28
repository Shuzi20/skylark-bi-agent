import pandas as pd
import requests
import streamlit as st
from datetime import datetime


MONDAY_API_URL = "https://api.monday.com/v2"


# ─────────────────────────────────────────
# FETCH FROM MONDAY.COM (Live, no cache)
# ─────────────────────────────────────────

def fetch_board_items(board_id):
    """
    Fetch all items from a Monday.com board via GraphQL.
    Returns raw JSON response.
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

    return data


def fetch_deals_live():
    """Fetch Deals board from Monday.com. Always fresh."""
    return fetch_board_items(st.secrets["MONDAY_DEALS_BOARD_ID"])


def fetch_work_orders_live():
    """Fetch Work Orders board from Monday.com. Always fresh."""
    return fetch_board_items(st.secrets["MONDAY_WORK_ORDERS_BOARD_ID"])


# ─────────────────────────────────────────
# NORMALIZE DEALS
# ─────────────────────────────────────────

def normalize_deals(raw_response):
    """
    Parse raw Monday.com API response into a clean DataFrame.
    Handles all known data quality issues in the Deals board.
    Returns: (DataFrame, list of quality issue strings)
    """
    quality_issues = []
    deals = []

    try:
        items = raw_response["data"]["boards"][0]["items_page"]["items"]
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected API response structure: {e}")

    for item in items:
        # Build a column lookup: column id → text value
        cols = {cv["id"]: cv.get("text", "") for cv in item["column_values"]}

        deal = {
            "id": item["id"],
            "deal_name": item.get("name", "").strip(),
            "owner_code": None,
            "client_code": None,
            "deal_status": None,
            "close_date": None,
            "closure_probability": None,
            "deal_value": None,
            "tentative_close_date": None,
            "deal_stage": None,
            "product_deal": None,
            "sector": None,
            "created_date": None,
        }

        # ── Filter out duplicate header rows ──
        # Some rows have "Deal Status" as their status value (repeated header)
        status_raw = _get_col(cols, ["deal_status", "status4", "status"])
        if status_raw and status_raw.strip() == "Deal Status":
            continue  # Skip this row entirely

        # ── Deal Status ──
        if status_raw in ["Won", "Dead", "Open", "On Hold"]:
            deal["deal_status"] = status_raw
        elif status_raw:
            quality_issues.append(f"Deal '{deal['deal_name']}': Unknown status '{status_raw}'")
            deal["deal_status"] = status_raw

        # ── Owner & Client codes ──
        deal["owner_code"] = _get_col(cols, ["owner_code", "text", "text0"]) or None
        deal["client_code"] = _get_col(cols, ["client_code", "text1", "text6"]) or None

        # ── Closure Probability ──
        prob_raw = _get_col(cols, ["closure_probability", "status_1", "status2"])
        if prob_raw in ["High", "Medium", "Low"]:
            deal["closure_probability"] = prob_raw
        elif prob_raw:
            quality_issues.append(f"Deal '{deal['deal_name']}': Unknown probability '{prob_raw}'")
        else:
            quality_issues.append(f"Deal '{deal['deal_name']}': Missing closure probability")

        # ── Deal Value ──
        val_raw = _get_col(cols, ["masked_deal_value", "numeric", "numbers"])
        deal["deal_value"] = _parse_number(val_raw)
        if deal["deal_value"] is None:
            quality_issues.append(f"Deal '{deal['deal_name']}': Missing deal value")

        # ── Dates ──
        close_raw = _get_col(cols, ["close_date_a_", "date", "date4"])
        tentative_raw = _get_col(cols, ["tentative_close_date", "date0", "date6"])

        deal["close_date"] = _parse_date(close_raw)
        deal["tentative_close_date"] = _parse_date(tentative_raw)

        if not deal["close_date"] and not deal["tentative_close_date"]:
            quality_issues.append(f"Deal '{deal['deal_name']}': Missing all close dates")

        # ── Other fields ──
        deal["deal_stage"] = _get_col(cols, ["deal_stage", "text2", "dropdown"]) or None
        deal["product_deal"] = _get_col(cols, ["product_deal", "text3", "color"]) or None
        deal["sector"] = _get_col(cols, ["sector_service", "sector", "text4", "dropdown0"]) or None
        deal["created_date"] = _parse_date(_get_col(cols, ["created_date", "date2", "date1"]))

        deals.append(deal)

    df = pd.DataFrame(deals)

    # Final cleanup
    if "sector" in df.columns:
        df["sector"] = df["sector"].str.strip().str.title()
    if "deal_status" in df.columns:
        df["deal_status"] = df["deal_status"].str.strip()

    return df, quality_issues


# ─────────────────────────────────────────
# NORMALIZE WORK ORDERS
# ─────────────────────────────────────────

def normalize_work_orders(raw_response):
    """
    Parse raw Monday.com API response into a clean Work Orders DataFrame.
    Handles 0.0-as-missing in financial fields, typo fixes, etc.
    Returns: (DataFrame, list of quality issue strings)
    """
    quality_issues = []
    orders = []

    try:
        items = raw_response["data"]["boards"][0]["items_page"]["items"]
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected API response structure: {e}")

    for item in items:
        cols = {cv["id"]: cv.get("text", "") for cv in item["column_values"]}

        order = {
            "id": item["id"],
            "deal_name": item.get("name", "").strip(),
            "customer_code": None,
            "serial_number": None,
            "nature_of_work": None,
            "execution_status": None,
            "sector": None,
            "type_of_work": None,
            "amount_excl_gst": None,
            "amount_incl_gst": None,
            "billed_excl_gst": None,
            "billed_incl_gst": None,
            "collected_amount": None,
            "amount_to_bill_excl": None,
            "amount_receivable": None,
            "billing_status": None,
            "wo_status": None,
            "invoice_status": None,
            "probable_start_date": None,
            "probable_end_date": None,
            "data_delivery_date": None,
        }

        # ── Text fields ──
        order["customer_code"] = _get_col(cols, ["customer_name_code", "text", "text0"]) or None
        order["serial_number"] = _get_col(cols, ["serial__", "text1", "text2"]) or None
        order["nature_of_work"] = _get_col(cols, ["nature_of_work", "dropdown", "text3"]) or None
        order["type_of_work"] = _get_col(cols, ["type_of_work", "text4", "dropdown0"]) or None

        # ── Execution Status (normalize variants) ──
        exec_raw = _get_col(cols, ["execution_status", "status", "status4"])
        order["execution_status"] = _normalize_execution_status(exec_raw)
        if not order["execution_status"]:
            quality_issues.append(f"Order '{order['deal_name']}': Missing execution status")

        # ── Sector ──
        order["sector"] = _get_col(cols, ["sector", "text5", "dropdown1"]) or None

        # ── Financial fields (treat 0.0 as missing) ──
        fin_map = {
            "amount_excl_gst": ["amount_in_rupees__excl_of_gst___masked_", "numeric", "numbers"],
            "amount_incl_gst": ["amount_in_rupees__incl_of_gst___masked_", "numeric0", "numbers0"],
            "billed_excl_gst": ["billed_value_in_rupees__excl_of_gst____masked_", "numeric1"],
            "billed_incl_gst": ["billed_value_in_rupees__incl_of_gst____masked_", "numeric2"],
            "collected_amount": ["collected_amount_in_rupees__incl_of_gst____masked_", "numeric3"],
            "amount_to_bill_excl": ["amount_to_be_billed_in_rs___exl__of_gst___masked_", "numeric4"],
            "amount_receivable": ["amount_receivable__masked_", "numeric5"],
        }
        for field, col_ids in fin_map.items():
            raw = _get_col(cols, col_ids)
            val = _parse_number(raw)
            # CRITICAL: treat 0.0 as missing, not zero
            if val is not None and val > 0:
                order[field] = val
            else:
                if val == 0:
                    quality_issues.append(f"Order '{order['deal_name']}': {field} is 0 (treated as missing)")

        # ── Billing Status — fix typo 'BIlled' → 'Billed' ──
        billing_raw = _get_col(cols, ["billing_status", "text6", "status2"])
        if billing_raw:
            order["billing_status"] = billing_raw.replace("BIlled", "Billed").strip()

        # ── WO Status ──
        order["wo_status"] = _get_col(cols, ["wo_status__billed_", "text7", "status3"]) or None

        # ── Invoice Status ──
        order["invoice_status"] = _get_col(cols, ["invoice_status", "status0", "status1"]) or None

        # ── Dates ──
        order["probable_start_date"] = _parse_date(_get_col(cols, ["probable_start_date", "date0", "date"]))
        order["probable_end_date"] = _parse_date(_get_col(cols, ["probable_end_date", "date1", "date2"]))
        order["data_delivery_date"] = _parse_date(_get_col(cols, ["data_delivery_date", "date3", "date4"]))

        orders.append(order)

    df = pd.DataFrame(orders)

    if "sector" in df.columns:
        df["sector"] = df["sector"].str.strip().str.title()

    return df, quality_issues


# ─────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────

def fetch_and_normalize_all():
    """
    Fetch both boards fresh from Monday.com, normalize, return clean DataFrames.
    Returns: (deals_df, orders_df, quality_issues, trace_info)
    """
    import time
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
    deals_df, deals_quality = normalize_deals(raw_deals)
    orders_df, orders_quality = normalize_work_orders(raw_orders)
    trace_info["normalize_time"] = round(time.time() - t0, 2)

    trace_info["deals_count"] = len(deals_df)
    trace_info["orders_count"] = len(orders_df)
    trace_info["quality_issues_count"] = len(deals_quality) + len(orders_quality)

    all_quality = deals_quality + orders_quality

    return deals_df, orders_df, all_quality, trace_info


# ─────────────────────────────────────────
# INSIGHTS GENERATOR
# ─────────────────────────────────────────

def generate_insights(deals_df, orders_df):
    """
    Calculate key business metrics from clean DataFrames.
    Returns a dictionary of insights for the LLM context.
    """
    insights = {}

    # ── Deals insights ──
    insights["total_deals"] = len(deals_df)

    if "deal_status" in deals_df.columns:
        insights["deals_by_status"] = deals_df["deal_status"].value_counts().to_dict()

    if "sector" in deals_df.columns:
        insights["deals_by_sector"] = deals_df["sector"].value_counts().to_dict()

    if "closure_probability" in deals_df.columns:
        insights["deals_by_probability"] = deals_df["closure_probability"].value_counts().to_dict()
        insights["missing_probability"] = int(deals_df["closure_probability"].isna().sum())

    if "deal_value" in deals_df.columns:
        valid_values = deals_df["deal_value"].dropna()
        insights["deals_with_values"] = len(valid_values)
        insights["missing_deal_values"] = len(deals_df) - len(valid_values)
        if len(valid_values) > 0:
            insights["total_pipeline_value"] = float(valid_values.sum())
            insights["avg_deal_value"] = float(valid_values.mean())

    # ── Work Orders insights ──
    insights["total_work_orders"] = len(orders_df)

    if "execution_status" in orders_df.columns:
        insights["orders_by_status"] = orders_df["execution_status"].value_counts().to_dict()

    if "sector" in orders_df.columns:
        insights["orders_by_sector"] = orders_df["sector"].value_counts().to_dict()

    if "collected_amount" in orders_df.columns:
        collected = orders_df["collected_amount"].dropna()
        insights["total_collected"] = float(collected.sum()) if len(collected) > 0 else 0

    if "amount_receivable" in orders_df.columns:
        receivable = orders_df["amount_receivable"].dropna()
        insights["total_receivable"] = float(receivable.sum()) if len(receivable) > 0 else 0

    if "amount_excl_gst" in orders_df.columns:
        total_contract = orders_df["amount_excl_gst"].dropna()
        insights["total_contract_value"] = float(total_contract.sum()) if len(total_contract) > 0 else 0

    return insights


# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────

def _get_col(cols_dict, possible_ids):
    """Try multiple possible column IDs, return first non-empty value found."""
    for col_id in possible_ids:
        val = cols_dict.get(col_id, "")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _parse_number(val):
    """Parse a value as float. Returns None if not parseable or zero."""
    if val is None or val == "":
        return None
    try:
        num = float(str(val).replace(",", "").strip())
        return num if num != 0.0 else None
    except (ValueError, TypeError):
        return None


def _parse_date(val):
    """Parse various date string formats. Returns date object or None."""
    if not val or str(val).strip() in ["", "nan", "None", "NaT"]:
        return None
    val = str(val).strip()
    formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
               "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%b %d", "%d %b %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(val[:10], fmt[:len(val[:10])]).date()
        except ValueError:
            continue
    return None


def _normalize_execution_status(raw):
    """Normalize the many variants of execution status to standard categories."""
    if not raw:
        return None
    raw = raw.strip()
    if any(x in raw for x in ["Completed", "Executed"]):
        return "Completed"
    elif "Not Started" in raw:
        return "Not Started"
    elif any(x in raw for x in ["Ongoing", "In Progress"]):
        return "Ongoing"
    elif "Partial" in raw:
        return "Partial Completed"
    elif any(x in raw for x in ["Pause", "struck", "Hold"]):
        return "Paused"
    elif "Details pending" in raw:
        return "Details Pending"
    else:
        return raw  # Keep unknown values as-is