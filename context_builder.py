# context_builder.py
# Builds pre-computed stats passed to the LLM as structured context.
# No keyword filtering — full data always sent so LLM can answer ANY question.

import json
import pandas as pd
import numpy as np
import streamlit as st


def _cr(value):
    """Convert raw rupees to crore string."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    cr = value / 10_000_000
    return f"Rs {cr:.2f} Cr"


def build_deals_context(deals_df):
    """
    Pre-compute ALL deal metrics:
    - Overall summary
    - Per-sector: total, status breakdown, probability per status, value stats
    - Win rates (won / won+dead)
    - Open deals detail
    """
    ctx = {}

    total = len(deals_df)
    ctx["total_deals"] = total

    # ── Overall status ──
    ctx["overall_status"] = deals_df["deal_status"].value_counts().to_dict()

    # ── Overall value ──
    all_vals = deals_df["deal_value"].dropna()
    all_vals = all_vals[all_vals > 0]
    ctx["total_pipeline_value"] = _cr(all_vals.sum()) if len(all_vals) else "N/A"
    ctx["deals_with_values"] = len(all_vals)
    ctx["deals_missing_values"] = total - len(all_vals)
    ctx["pct_missing_values"] = f"{round((total - len(all_vals)) / max(total, 1) * 100)}%"

    # ── Overall probability ──
    prob_counts = deals_df["closure_probability"].value_counts().to_dict()
    ctx["closure_probability_overall"] = {
        "High": prob_counts.get("High", 0),
        "Medium": prob_counts.get("Medium", 0),
        "Low": prob_counts.get("Low", 0),
        "missing": int(deals_df["closure_probability"].isna().sum()),
        "pct_missing": f"{round(deals_df['closure_probability'].isna().sum() / max(total,1) * 100)}%"
    }

    # ── Per-sector deep stats ──
    sector_stats = {}
    for sector in sorted(deals_df["sector"].dropna().unique()):
        s = deals_df[deals_df["sector"] == sector]
        won = len(s[s["deal_status"] == "Won"])
        dead = len(s[s["deal_status"] == "Dead"])
        open_ = len(s[s["deal_status"] == "Open"])
        on_hold = len(s[s["deal_status"] == "On Hold"])
        total_closed = won + dead

        vals = s["deal_value"].dropna()
        vals = vals[vals > 0]

        # Probability ONLY for open deals (not all deals)
        open_deals = s[s["deal_status"] == "Open"]
        open_prob = open_deals["closure_probability"].value_counts().to_dict()
        open_unrated = int(open_deals["closure_probability"].isna().sum())

        sector_stats[sector] = {
            "total": len(s),
            "won": won,
            "dead": dead,
            "open": open_,
            "on_hold": on_hold,
            "win_rate": f"{round(won / total_closed * 100, 1)}%" if total_closed > 0 else "N/A (no closed deals)",
            "open_deals_probability": {
                **open_prob,
                "unrated": open_unrated
            },
            "deals_with_values": len(vals),
            "deals_missing_values": len(s) - len(vals),
            "total_value": _cr(vals.sum()) if len(vals) else "N/A",
            "avg_value": _cr(vals.mean()) if len(vals) else "N/A",
            "max_value": _cr(vals.max()) if len(vals) else "N/A",
        }

    ctx["by_sector"] = sector_stats

    # ── Win rate ranking ──
    win_rate_rank = sorted(
        [
            {"sector": k, "win_rate_pct": v["win_rate"], "won": v["won"], "total": v["total"]}
            for k, v in sector_stats.items()
            if v["win_rate"] != "N/A (no closed deals)"
        ],
        key=lambda x: float(x["win_rate_pct"].replace("%", "")) if "%" in str(x["win_rate_pct"]) else 0,
        reverse=True
    )
    ctx["win_rate_ranking"] = win_rate_rank

    # ── On hold deals detail ──
    oh = deals_df[deals_df["deal_status"] == "On Hold"]
    ctx["on_hold_deals"] = [
        {
            "name": row["deal_name"],
            "sector": row["sector"],
            "probability": row["closure_probability"] if pd.notna(row.get("closure_probability")) else "unrated",
            "value": _cr(row["deal_value"]) if pd.notna(row.get("deal_value")) and row.get("deal_value", 0) > 0 else "N/A"
        }
        for _, row in oh.iterrows()
    ]

    # ── Open deals detail (top 20) ──
    open_deals_df = deals_df[deals_df["deal_status"] == "Open"].head(20)
    ctx["open_deals_sample"] = [
        {
            "name": row["deal_name"],
            "sector": row["sector"],
            "probability": row["closure_probability"] if pd.notna(row.get("closure_probability")) else "unrated",
            "value": _cr(row["deal_value"]) if pd.notna(row.get("deal_value")) and row.get("deal_value", 0) > 0 else "N/A",
            "stage": row.get("deal_stage")
        }
        for _, row in open_deals_df.iterrows()
    ]

    return ctx


def build_orders_context(orders_df):
    """
    Pre-compute ALL work order metrics:
    - Overall execution status, sector breakdown
    - Financial totals: contract, collected, receivable, billed
    - Collection rate
    - Per-sector deep financials
    - Billing/WO status breakdown
    """
    ctx = {}

    ctx["total_work_orders"] = len(orders_df)
    ctx["execution_status_overall"] = orders_df["execution_status"].value_counts().to_dict()
    ctx["sector_count"] = orders_df["sector"].value_counts().to_dict()

    # ── Overall financials ──
    def safe_sum(col):
        if col not in orders_df.columns:
            return None
        v = orders_df[col].dropna()
        v = v[v > 0]
        return float(v.sum()) if len(v) > 0 else None

    total_contract = safe_sum("amount_excl_gst")
    total_collected = safe_sum("collected_amount")
    total_receivable = safe_sum("amount_receivable")
    total_billed = safe_sum("billed_excl_gst")
    total_contract_incl = safe_sum("amount_incl_gst")

    ctx["financials"] = {
        "total_contract_excl_gst": _cr(total_contract),
        "total_contract_incl_gst": _cr(total_contract_incl),
        "total_collected_incl_gst": _cr(total_collected),
        "total_receivable": _cr(total_receivable),
        "total_billed_excl_gst": _cr(total_billed),
        "collection_rate": f"{round(total_collected / total_contract_incl * 100, 1)}% (collected / contract incl GST)"
                           if total_collected and total_contract_incl else "N/A",
        "wos_with_contract_value": len(orders_df["amount_excl_gst"].dropna()),
        "wos_missing_contract_value": len(orders_df) - len(orders_df["amount_excl_gst"].dropna()),
    }

    # ── Per-sector work order stats ──
    sector_stats = {}
    for sector in sorted(orders_df["sector"].dropna().unique()):
        s = orders_df[orders_df["sector"] == sector]
        exec_counts = s["execution_status"].value_counts().to_dict()

        c = s["collected_amount"].dropna()
        c = c[c > 0]
        r = s["amount_receivable"].dropna()
        r = r[r > 0]
        a = s["amount_excl_gst"].dropna()
        a = a[a > 0]
        b = s["billed_excl_gst"].dropna()
        b = b[b > 0]

        coll_rate = None
        a_incl = s["amount_incl_gst"].dropna()
        a_incl = a_incl[a_incl > 0]
        if len(c) > 0 and len(a_incl) > 0:
            coll_rate = f"{round(c.sum() / a_incl.sum() * 100, 1)}%"

        sector_stats[sector] = {
            "total_orders": len(s),
            "execution_status": exec_counts,
            "contract_value_excl_gst": _cr(a.sum()) if len(a) > 0 else "N/A",
            "collected": _cr(c.sum()) if len(c) > 0 else "N/A",
            "receivable": _cr(r.sum()) if len(r) > 0 else "N/A",
            "billed_excl_gst": _cr(b.sum()) if len(b) > 0 else "N/A",
            "collection_rate": coll_rate if coll_rate else "N/A",
        }

    ctx["by_sector"] = sector_stats

    # ── Billing status breakdown ──
    if "billing_status" in orders_df.columns:
        ctx["billing_status_breakdown"] = orders_df["billing_status"].value_counts().to_dict()

    # ── WO status (open/closed) ──
    if "wo_status" in orders_df.columns:
        ctx["wo_status_breakdown"] = orders_df["wo_status"].value_counts().to_dict()

    return ctx


def build_full_context(deals_df, orders_df, question, quality_summary, chat_history):
    """
    Assemble final JSON context dict for the LLM.
    """
    deals_ctx = build_deals_context(deals_df)
    orders_ctx = build_orders_context(orders_df)

    quality_notes = [
        f"{quality_summary.get('missing_deal_value', 0)} deals missing deal value ({quality_summary.get('pct_missing_value', '?')})",
        f"{quality_summary.get('missing_closure_probability', 0)} deals missing closure probability ({quality_summary.get('pct_missing_probability', '?')})",
        f"{quality_summary.get('missing_close_dates', 0)} deals missing close dates — tentative used as fallback",
        f"{quality_summary.get('skipped_header_rows', 0)} duplicate header rows removed from source data",
        f"{quality_summary.get('billing_typos_fixed', 0)} billing status typos fixed (BIlled → Billed)",
        "Financial values of 0 treated as missing/not entered — not actual zero revenue",
    ]

    return {
        "question": question,
        "previous_conversation": chat_history or "First question in session.",
        "deals": deals_ctx,
        "work_orders": orders_ctx,
        "data_quality_notes": quality_notes,
    }