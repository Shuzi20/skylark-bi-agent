# context_builder.py
# Builds pre-computed stats passed to the LLM as structured context.
# Interpretation logic lives HERE — not in the prompt.
# Prompt only formats and presents. This layer computes and interprets.
#
# Updates:
# [1] quarterly_pipeline added — enables last quarter comparison
# [2] value_distribution added — enables threshold filter answers
# [3] active_filters passed through to context so LLM sees them

import json
import pandas as pd
import numpy as np
from datetime import timedelta


def _cr(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    cr = value / 10_000_000
    return f"Rs {cr:.2f} Cr"


# ─────────────────────────────────────────
# INTERPRETATION HELPERS
# ─────────────────────────────────────────

def _interpret_velocity(velocity_dict):
    if not velocity_dict:
        return "insufficient data"
    counts = [v["deals_created"] for v in velocity_dict.values()]
    months = list(velocity_dict.keys())
    if len(counts) < 2:
        return "insufficient data"
    max_val = max(counts)
    avg_others = (sum(counts) - max_val) / max(len(counts) - 1, 1)
    if max_val > 0 and avg_others > 0 and max_val >= 5 * avg_others:
        spike_month = months[counts.index(max_val)]
        return f"SPIKE in {spike_month} ({max_val} deals) — likely batch entry or real growth burst. Treat with caution."
    if all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)):
        return "SLOWDOWN — deal creation declining month over month"
    if all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1)):
        return "GROWTH — deal creation accelerating"
    return "MIXED — no clear trend across available months"


def _flag_collection_rates(sector_stats):
    urgent, healthy = [], []
    for sector, stats in sector_stats.items():
        rate_str = stats.get("collection_rate", "N/A")
        total_orders = stats.get("total_orders", 0)
        if rate_str == "N/A" or total_orders < 3:
            continue
        try:
            rate = float(rate_str.replace("%", ""))
        except (ValueError, TypeError):
            continue
        if rate < 5:
            urgent.append({
                "sector": sector,
                "collection_rate": rate_str,
                "receivable_stuck": stats.get("receivable", "N/A"),
                "total_orders": total_orders
            })
        elif rate >= 60:
            healthy.append({"sector": sector, "collection_rate": rate_str})
    return {"urgent_blockers": urgent, "healthy_sectors": healthy}


def _quarter_label(i):
    return "this_quarter" if i == 0 else f"last_{i}_quarter{'s' if i > 1 else ''}_ago"


# ─────────────────────────────────────────
# DEALS CONTEXT
# ─────────────────────────────────────────

def build_deals_context(deals_df):
    deals_df = deals_df.copy()
    for col in ["created_date", "close_date", "tentative_close_date"]:
        if col in deals_df.columns:
            deals_df[col] = pd.to_datetime(deals_df[col], errors="coerce")

    ctx = {}
    total = len(deals_df)
    ctx["total_deals"] = total
    ctx["overall_status"] = deals_df["deal_status"].value_counts().to_dict()

    all_vals = deals_df["deal_value"].dropna()
    all_vals = all_vals[all_vals > 0]
    ctx["total_pipeline_value"] = _cr(all_vals.sum()) if len(all_vals) else "N/A"
    ctx["deals_with_values"] = len(all_vals)
    ctx["deals_missing_values"] = total - len(all_vals)
    ctx["pct_missing_values"] = f"{round((total - len(all_vals)) / max(total, 1) * 100)}%"

    # ── Value distribution — enables threshold filter answers ──
    if len(all_vals) > 0:
        ctx["value_distribution"] = {
            "min_deal_value": _cr(all_vals.min()),
            "max_deal_value": _cr(all_vals.max()),
            "median_deal_value": _cr(all_vals.median()),
            "deals_above_1cr": int((all_vals >= 10_000_000).sum()),
            "deals_above_50L": int((all_vals >= 5_000_000).sum()),
            "deals_above_10L": int((all_vals >= 1_000_000).sum()),
            "deals_above_1L": int((all_vals >= 100_000).sum()),
            "deals_above_50k": int((all_vals >= 50_000).sum()),
            "note": "All deals with values are above Rs 50,000 — threshold filters below Rs 50k have no effect"
        }

    prob_counts = deals_df["closure_probability"].value_counts().to_dict()
    ctx["closure_probability_overall"] = {
        "High": prob_counts.get("High", 0),
        "Medium": prob_counts.get("Medium", 0),
        "Low": prob_counts.get("Low", 0),
        "missing": int(deals_df["closure_probability"].isna().sum()),
        "pct_missing": f"{round(deals_df['closure_probability'].isna().sum() / max(total, 1) * 100)}%"
    }

    # ── Per-sector stats ──
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
        open_deals = s[s["deal_status"] == "Open"]
        open_prob = open_deals["closure_probability"].value_counts().to_dict()
        open_unrated = int(open_deals["closure_probability"].isna().sum())
        win_rate = f"{round(won / total_closed * 100, 1)}%" if total_closed > 0 else "N/A (no closed deals)"
        insufficient = total_closed < 5
        sector_stats[sector] = {
            "total": len(s),
            "won": won,
            "dead": dead,
            "open": open_,
            "on_hold": on_hold,
            "total_closed": total_closed,
            "win_rate": win_rate,
            "insufficient_sample": insufficient,
            "open_deals_probability": {**open_prob, "unrated": open_unrated},
            "deals_with_values": len(vals),
            "deals_missing_values": len(s) - len(vals),
            "total_value": _cr(vals.sum()) if len(vals) else "N/A",
            "avg_value": _cr(vals.mean()) if len(vals) else "N/A",
        }
    ctx["by_sector"] = sector_stats

    # ── Win rate ranking ──
    ctx["win_rate_ranking"] = sorted(
        [
            {
                "sector": k,
                "win_rate": v["win_rate"],
                "won": v["won"],
                "total_closed": v["total_closed"],
                "note": "insufficient sample (<5 closed deals)" if v["insufficient_sample"] else ""
            }
            for k, v in sector_stats.items()
            if v["win_rate"] != "N/A (no closed deals)"
        ],
        key=lambda x: float(x["win_rate"].replace("%", "")) if "%" in str(x["win_rate"]) else 0,
        reverse=True
    )

    # ── On Hold deals ──
    oh = deals_df[deals_df["deal_status"] == "On Hold"]
    ctx["on_hold_deals"] = [
        {
            "name": row["deal_name"],
            "sector": row["sector"],
            "probability": row["closure_probability"] if pd.notna(row.get("closure_probability")) else "unrated"
        }
        for _, row in oh.iterrows()
    ]

    # ── Funnel stage breakdown ──
    if "deal_stage" in deals_df.columns:
        stage_funnel = {
            "Top of Funnel (Lead/SQL/Demo)": ["A. Lead Generated", "B. Sales Qualified Leads", "C. Demo Done"],
            "Mid Funnel (Proposal/Negotiation)": ["D. Feasibility", "E. Proposal/Commercials Sent", "F. Negotiations"],
            "Late Stage (Won/WO/POC)": ["G. Project Won", "H. Work Order Received", "I. POC"],
            "Closed Won (Billing)": ["Project Completed", "J. Invoice sent", "K. Amount Accrued"],
            "Closed Lost": ["L. Project Lost", "M. Projects On Hold", "N. Not relevant at the moment", "O. Not Relevant at all"],
        }
        ctx["funnel_stage_breakdown"] = {
            group: len(deals_df[deals_df["deal_stage"].isin(stages)])
            for group, stages in stage_funnel.items()
        }

    # ── TIME-BASED VELOCITY + QUARTERLY PIPELINE ──
    if "created_date" in deals_df.columns:
        deals_with_dates = deals_df[deals_df["created_date"].notna()].copy()
        if len(deals_with_dates) > 0:
            now = deals_df["created_date"].max()

            # Monthly velocity
            velocity = {}
            for i in range(3, 0, -1):
                start = now - timedelta(days=30 * i)
                end = now - timedelta(days=30 * (i - 1))
                label = start.strftime("%b %Y")
                created = len(deals_with_dates[
                    (deals_with_dates["created_date"] >= start) &
                    (deals_with_dates["created_date"] < end)
                ])
                velocity[label] = {"deals_created": created}
            ctx["deal_creation_velocity_last_3_months"] = velocity
            ctx["velocity_interpretation"] = _interpret_velocity(velocity)

            # Wins per month
            won_df = deals_df[deals_df["deal_status"] == "Won"].copy()
            won_df = won_df[won_df["close_date"].notna()]
            wins_by_month = {}
            for i in range(3, 0, -1):
                start = now - timedelta(days=30 * i)
                end = now - timedelta(days=30 * (i - 1))
                label = start.strftime("%b %Y")
                wins = len(won_df[(won_df["close_date"] >= start) & (won_df["close_date"] < end)])
                wins_by_month[label] = wins
            ctx["wins_per_month_last_3_months"] = wins_by_month

            # ── QUARTERLY PIPELINE — enables Q vs Q comparisons ──
            quarterly = {}
            for i in range(4):
                q_end = now - timedelta(days=90 * i)
                q_start = now - timedelta(days=90 * (i + 1))
                label = "this_quarter" if i == 0 else f"{i}_quarter{'s' if i > 1 else ''}_ago"
                window = deals_with_dates[
                    (deals_with_dates["created_date"] >= q_start) &
                    (deals_with_dates["created_date"] < q_end)
                ]
                vals_q = window["deal_value"].dropna()
                vals_q = vals_q[vals_q > 0]
                won_q = len(window[window["deal_status"] == "Won"])
                dead_q = len(window[window["deal_status"] == "Dead"])
                wr_q = f"{round(won_q / (won_q + dead_q) * 100, 1)}%" if (won_q + dead_q) > 0 else "N/A"

                # Per-sector breakdown for this quarter
                sector_q = {}
                for sector in window["sector"].dropna().unique():
                    sw = window[window["sector"] == sector]
                    sv = sw["deal_value"].dropna()
                    sv = sv[sv > 0]
                    sector_q[sector] = {
                        "deals": len(sw),
                        "pipeline_value": _cr(sv.sum()) if len(sv) > 0 else "N/A",
                        "won": len(sw[sw["deal_status"] == "Won"])
                    }

                quarterly[label] = {
                    "period": f"{q_start.strftime('%d %b %Y')} to {q_end.strftime('%d %b %Y')}",
                    "total_deals_created": len(window),
                    "pipeline_value": _cr(vals_q.sum()) if len(vals_q) > 0 else "N/A",
                    "deals_with_values": len(vals_q),
                    "won_deals": won_q,
                    "dead_deals": dead_q,
                    "win_rate": wr_q,
                    "by_sector": sector_q
                }
            ctx["quarterly_pipeline"] = quarterly

            # QoQ change summary
            this_q_val = deals_df[
                (deals_df["created_date"] >= (now - timedelta(days=90))) &
                deals_df["deal_value"].notna() &
                (deals_df["deal_value"] > 0)
            ]["deal_value"]
            last_q_val = deals_df[
                (deals_df["created_date"] >= (now - timedelta(days=180))) &
                (deals_df["created_date"] < (now - timedelta(days=90))) &
                deals_df["deal_value"].notna() &
                (deals_df["deal_value"] > 0)
            ]["deal_value"]
            if len(last_q_val) > 0 and last_q_val.sum() > 0:
                pct_change = round((this_q_val.sum() - last_q_val.sum()) / last_q_val.sum() * 100, 1)
                ctx["qoq_pipeline_change"] = {
                    "this_quarter_value": _cr(this_q_val.sum()),
                    "last_quarter_value": _cr(last_q_val.sum()),
                    "pct_change": f"{'+' if pct_change >= 0 else ''}{pct_change}%",
                    "interpretation": "GROWTH" if pct_change > 10 else "DECLINE" if pct_change < -10 else "STABLE"
                }

            # Open deal aging
            open_d = deals_df[deals_df["deal_status"] == "Open"].copy()
            open_d = open_d[open_d["created_date"].notna()]
            if len(open_d) > 0:
                open_d["age_days"] = (now - open_d["created_date"]).dt.days
                ctx["open_deal_aging"] = {
                    "avg_age_days": round(open_d["age_days"].mean()),
                    "under_30_days": int(len(open_d[open_d["age_days"] <= 30])),
                    "30_to_60_days": int(len(open_d[(open_d["age_days"] > 30) & (open_d["age_days"] <= 60)])),
                    "60_to_90_days": int(len(open_d[(open_d["age_days"] > 60) & (open_d["age_days"] <= 90)])),
                    "over_90_days_stale": int(len(open_d[open_d["age_days"] > 90])),
                }

            # Avg days to close
            won_timed = deals_df[deals_df["deal_status"] == "Won"].copy()
            won_timed = won_timed[won_timed["created_date"].notna()]
            won_timed["close_date_dt"] = pd.to_datetime(won_timed["close_date"], errors="coerce")
            won_timed = won_timed[won_timed["close_date_dt"].notna()]
            if len(won_timed) > 0:
                won_timed["days_to_close"] = (won_timed["close_date_dt"] - won_timed["created_date"]).dt.days
                won_timed = won_timed[won_timed["days_to_close"] >= 0]
                if len(won_timed) > 0:
                    ctx["avg_days_to_close"] = {
                        "overall": round(won_timed["days_to_close"].mean()),
                        "note": "Avg calendar days from deal creation to won status"
                    }

    # ── Weighted pipeline forecast ──
    prob_map = {"High": 0.8, "Medium": 0.5, "Low": 0.2}
    open_vals = deals_df[(deals_df["deal_status"] == "Open") & deals_df["deal_value"].notna()].copy()
    open_vals = open_vals[open_vals["deal_value"] > 0]
    if len(open_vals) > 0:
        open_vals["prob_score"] = open_vals["closure_probability"].map(prob_map).fillna(0.1)
        open_vals["weighted"] = open_vals["deal_value"] * open_vals["prob_score"]
        ctx["weighted_pipeline_forecast"] = {
            "raw_open_pipeline": _cr(open_vals["deal_value"].sum()),
            "probability_adjusted_forecast": _cr(open_vals["weighted"].sum()),
            "open_deals_with_values": len(open_vals),
            "open_deals_total": len(deals_df[deals_df["deal_status"] == "Open"]),
            "methodology": "High=80%, Medium=50%, Low=20%, Unrated=10%"
        }

    return ctx


# ─────────────────────────────────────────
# WORK ORDERS CONTEXT
# ─────────────────────────────────────────

def build_orders_context(orders_df):
    ctx = {}
    ctx["total_work_orders"] = len(orders_df)
    ctx["execution_status_overall"] = orders_df["execution_status"].value_counts().to_dict()
    ctx["sector_count"] = orders_df["sector"].value_counts().to_dict()

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
        "collection_rate": f"{round(total_collected / total_contract_incl * 100, 1)}%"
                           if total_collected and total_contract_incl else "N/A",
        "wos_with_contract_value": len(orders_df["amount_excl_gst"].dropna()),
        "wos_missing_contract_value": len(orders_df) - len(orders_df["amount_excl_gst"].dropna()),
    }

    sector_stats = {}
    for sector in sorted(orders_df["sector"].dropna().unique()):
        s = orders_df[orders_df["sector"] == sector]
        exec_counts = s["execution_status"].value_counts().to_dict() if "execution_status" in s.columns else {}
        c = s["collected_amount"].dropna(); c = c[c > 0]
        r = s["amount_receivable"].dropna(); r = r[r > 0]
        a = s["amount_excl_gst"].dropna(); a = a[a > 0]
        b = s["billed_excl_gst"].dropna(); b = b[b > 0]
        a_incl = s["amount_incl_gst"].dropna(); a_incl = a_incl[a_incl > 0]
        coll_rate = f"{round(c.sum() / a_incl.sum() * 100, 1)}%" if len(c) > 0 and len(a_incl) > 0 else "N/A"
        sector_stats[sector] = {
            "total_orders": len(s),
            "execution_status": exec_counts,
            "contract_value_excl_gst": _cr(a.sum()) if len(a) > 0 else "N/A",
            "collected": _cr(c.sum()) if len(c) > 0 else "N/A",
            "receivable": _cr(r.sum()) if len(r) > 0 else "N/A",
            "billed_excl_gst": _cr(b.sum()) if len(b) > 0 else "N/A",
            "collection_rate": coll_rate,
        }
    ctx["by_sector"] = sector_stats
    ctx["collection_rate_flags"] = _flag_collection_rates(sector_stats)

    if "billing_status" in orders_df.columns:
        ctx["billing_status_breakdown"] = orders_df["billing_status"].value_counts().to_dict()
    if "wo_status" in orders_df.columns:
        ctx["wo_status_breakdown"] = orders_df["wo_status"].value_counts().to_dict()

    return ctx


# ─────────────────────────────────────────
# FULL CONTEXT ASSEMBLER
# ─────────────────────────────────────────

def build_full_context(deals_df, orders_df, question, quality_summary, chat_history, active_filters=None):
    deals_ctx = build_deals_context(deals_df)
    orders_ctx = build_orders_context(orders_df)

    quality_notes = [
        f"{quality_summary.get('missing_deal_value', 0)} deals missing deal value ({quality_summary.get('pct_missing_value', '?')})",
        f"{quality_summary.get('missing_closure_probability', 0)} deals missing closure probability ({quality_summary.get('pct_missing_probability', '?')})",
        f"{quality_summary.get('missing_close_dates', 0)} deals missing close dates",
        f"{quality_summary.get('skipped_header_rows', 0)} duplicate header rows removed",
        f"{quality_summary.get('billing_typos_fixed', 0)} billing status typos fixed",
        "Financial values of 0 treated as missing — not actual zero revenue",
    ]

    return {
        "question": question,
        "active_filters": active_filters or [],
        "previous_conversation": chat_history or "First question in session.",
        "deals": deals_ctx,
        "work_orders": orders_ctx,
        "data_quality_notes": quality_notes,
    }