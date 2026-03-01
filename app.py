# app.py
import streamlit as st
import time
from data_layer import fetch_and_normalize_all
from intelligence_layer import generate_answer, create_trace, extract_new_filters, format_filters_for_display

st.set_page_config(
    page_title="Skylark Drones BI Agent",
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #1E3A5F; margin-bottom: 0; }
    .sub-header  { font-size: 1rem; color: #444; margin-bottom: 1.5rem; }
    .user-message {
        background-color: #DBEAFE;
        border-left: 4px solid #2563EB;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
        color: #1E3A5F;
        font-size: 1rem;
    }
    .agent-message {
        background-color: #DCFCE7;
        border-left: 4px solid #16A34A;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
        color: #14532D;
        font-size: 1rem;
        line-height: 1.6;
    }
    .filter-badge {
        background-color: #FEF3C7;
        border: 1px solid #F59E0B;
        border-radius: 12px;
        padding: 2px 10px;
        font-size: 0.78rem;
        color: #92400E;
        display: inline-block;
        margin: 2px 3px;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "total_queries" not in st.session_state:
    st.session_state.total_queries = 0
if "pending_question" not in st.session_state:
    st.session_state.pending_question = None
if "active_filters" not in st.session_state:
    st.session_state.active_filters = []

# ─────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/drone.png", width=60)
    st.markdown("## Skylark BI Agent")
    st.markdown("---")

    st.markdown("### What you can ask")
    st.markdown("""
- How is our mining pipeline?
- Show open deals with high probability
- What is our total receivable amount?
- Which sectors have most completed work orders?
- What is the total value of won deals?
- Show renewable energy deals in proposal stage
- How many deals are on hold?
- What is our collection rate?
    """)
    st.markdown("---")

    st.markdown("### Data Info")
    st.markdown("""
- Deals board: 346 records
- Work Orders board: 177 records
- Freshness: Live API no cache
- AI Model: Llama 3.3 70B Groq
    """)
    st.markdown("---")

    # ── Active Filters Display ──
    if st.session_state.active_filters:
        st.markdown("### 🔍 Active Filters")
        for label in format_filters_for_display(st.session_state.active_filters):
            st.markdown(f"🔹 {label}")
        if st.button("✕ Clear All Filters", use_container_width=True):
            st.session_state.active_filters = []
            st.rerun()
        st.markdown("---")

    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.total_queries = 0
        st.session_state.pending_question = None
        st.session_state.active_filters = []
        st.rerun()

    st.markdown("---")
    st.markdown("### Monday.com Boards")
    deals_id = st.secrets.get("MONDAY_DEALS_BOARD_ID", "")
    orders_id = st.secrets.get("MONDAY_WORK_ORDERS_BOARD_ID", "")
    if deals_id:
        st.markdown(f"[Deals Board](https://bhanotshruti20s-team.monday.com/boards/{deals_id})")
    if orders_id:
        st.markdown(f"[Work Orders Board](https://bhanotshruti20s-team.monday.com/boards/{orders_id})")
    st.markdown("---")
    st.caption(f"Queries this session: {st.session_state.total_queries}")

# ─────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────
st.markdown('<p class="main-header">Skylark Drones BI Agent</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Ask founder-level questions about your deal pipeline and work orders. Data fetched live from Monday.com.</p>', unsafe_allow_html=True)

# ─────────────────────────────────────────
# SAMPLE QUESTIONS (shown only on first load)
# ─────────────────────────────────────────
if len(st.session_state.messages) == 0 and st.session_state.pending_question is None:
    st.markdown("#### Try asking:")
    sample_questions = [
        "How is our mining pipeline?",
        "Show open deals with high probability",
        "What is our total receivable amount?",
        "Which sectors have completed work orders?",
        "What is the total value of won deals?",
        "How many deals are on hold?",
    ]
    cols = st.columns(3)
    for i, q in enumerate(sample_questions):
        with cols[i % 3]:
            if st.button(q, key=f"sample_{i}", use_container_width=True):
                st.session_state.pending_question = q
                st.rerun()
    st.markdown("---")

# ─────────────────────────────────────────
# CHAT HISTORY DISPLAY
# ─────────────────────────────────────────
for message in st.session_state.messages:
    if message["role"] == "user":
        st.markdown(
            f'<div class="user-message"><strong>You:</strong> {message["content"]}</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="agent-message"><strong>Agent:</strong></div>',
            unsafe_allow_html=True
        )
        st.markdown(message["content"])

        # Show which filters were active for this answer
        if message.get("filters_applied"):
            labels = format_filters_for_display(message["filters_applied"])
            if labels:
                badges = " ".join(f'<span class="filter-badge">🔹 {l}</span>' for l in labels)
                st.markdown(f'<div style="margin:4px 0 8px 0">{badges}</div>', unsafe_allow_html=True)

        if "trace" in message:
            with st.expander("Show API Trace", expanded=False):
                st.code(message["trace"], language="text")

        if "caveats" in message and message["caveats"]:
            with st.expander("Data Quality Notes", expanded=False):
                for caveat in message["caveats"]:
                    st.warning(caveat)

        st.markdown("---")

# ─────────────────────────────────────────
# INPUT BAR
# ─────────────────────────────────────────
col1, col2 = st.columns([5, 1])
with col1:
    user_question = st.text_input(
        "Ask a question:",
        placeholder="e.g. Show me mining deals... or 'Now exclude energy' or 'Compare to last quarter'",
        label_visibility="collapsed",
        key="question_input"
    )
with col2:
    ask_button = st.button("Ask", use_container_width=True, type="primary")

final_question = None

if st.session_state.pending_question:
    final_question = st.session_state.pending_question
    st.session_state.pending_question = None
elif ask_button:
    if user_question.strip():
        final_question = user_question.strip()
    else:
        st.warning("Please type a question first!")

# ─────────────────────────────────────────
# PROCESS QUESTION
# ─────────────────────────────────────────
def process_question(q):
    st.session_state.messages.append({"role": "user", "content": q})

    with st.spinner("Fetching live data from Monday.com and analyzing..."):
        try:
            deals_df, orders_df, quality_summary, trace_info = fetch_and_normalize_all()

            # Build chat history string from last 5 exchanges
            recent = st.session_state.messages[-10:-1]
            chat_history = "\n".join([
                f"{'Founder' if m['role'] == 'user' else 'Agent'}: {m['content'][:200]}"
                for m in recent
            ]) if recent else ""

            # ── Step 1: Update active filters from this question ──
            st.session_state.active_filters = extract_new_filters(
                q,
                st.session_state.active_filters
            )
            current_filters = list(st.session_state.active_filters)

            # ── Step 2: Generate answer with active filters passed in ──
            llm_start = time.time()
            answer = generate_answer(
                question=q,
                deals_df=deals_df,
                orders_df=orders_df,
                chat_history=chat_history,
                quality_summary=quality_summary,
                active_filters=current_filters
            )
            trace_info["llm_time"] = round(time.time() - llm_start, 2)

            # ── Step 3: Build trace showing active filters ──
            trace = create_trace(
                trace_info=trace_info,
                quality_summary=quality_summary,
                question=q,
                active_filters=current_filters
            )

            caveats = [
                f"{quality_summary.get('missing_deal_value', 0)} deals missing deal value ({quality_summary.get('pct_missing_value', '?')})",
                f"{quality_summary.get('missing_closure_probability', 0)} deals missing closure probability ({quality_summary.get('pct_missing_probability', '?')})",
                f"{quality_summary.get('missing_close_dates', 0)} deals missing close dates — tentative used as fallback",
                f"{quality_summary.get('skipped_header_rows', 0)} duplicate header rows removed",
                f"{quality_summary.get('billing_typos_fixed', 0)} billing typo(s) auto-corrected",
            ]

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "trace": trace,
                "caveats": caveats,
                "filters_applied": current_filters,
            })
            st.session_state.total_queries += 1

        except Exception as e:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"⚠️ Error: {str(e)}\n\nCheck your API keys in .streamlit/secrets.toml",
                "trace": f"ERROR: {str(e)}",
                "caveats": [],
                "filters_applied": [],
            })

    st.rerun()


if final_question:
    process_question(final_question)

st.markdown("---")
st.caption("Built for Skylark Drones · Powered by Groq Llama 3.3 70B · Data from Monday.com (live)")