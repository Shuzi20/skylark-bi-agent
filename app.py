import streamlit as st
import time
from data_layer import fetch_and_normalize_all
from intelligence_layer import generate_answer, create_trace

# ─────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────

st.set_page_config(
    page_title="Skylark Drones BI Agent",
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────

st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1E3A5F;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .user-message {
        background-color: #E8F4FD;
        border-left: 4px solid #2196F3;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }
    .agent-message {
        background-color: #F0F7F0;
        border-left: 4px solid #4CAF50;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }
    .caveat-box {
        background-color: #FFF8E1;
        border-left: 4px solid #FFC107;
        padding: 8px 12px;
        border-radius: 0 6px 6px 0;
        font-size: 0.85rem;
        margin-top: 6px;
    }
    .stTextInput > div > div > input {
        border-radius: 8px;
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

# ─────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/color/96/drone.png", width=60)
    st.markdown("## 🚁 Skylark BI Agent")
    st.markdown("---")

    st.markdown("### 📊 What you can ask")
    st.markdown("""
- *How's our mining pipeline?*
- *Show open deals with high probability*
- *What's our total receivable amount?*
- *Which sectors have most completed work orders?*
- *What's the total value of won deals?*
- *Show renewable energy deals in proposal stage*
- *How many deals are on hold?*
- *What's our collection rate?*
    """)

    st.markdown("---")
    st.markdown("### ⚡ Data Info")
    st.markdown("""
- **Deals board:** 346 records
- **Work Orders board:** 177 records  
- **Freshness:** Live API (no cache)
- **AI Model:** Llama 3.3 70B (Groq)
    """)

    st.markdown("---")

    # Clear chat button
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.total_queries = 0
        st.rerun()

    st.markdown("---")
    st.markdown("### 🔗 Monday.com Boards")
    st.markdown(f"[📋 Deals Board](https://bhanotshruti20s-team.monday.com/boards/{st.secrets.get('MONDAY_DEALS_BOARD_ID', '')})")
    st.markdown(f"[📋 Work Orders Board](https://bhanotshruti20s-team.monday.com/boards/{st.secrets.get('MONDAY_WORK_ORDERS_BOARD_ID', '')})")

    st.markdown("---")
    st.caption(f"Queries this session: {st.session_state.total_queries}")

# ─────────────────────────────────────────
# MAIN HEADER
# ─────────────────────────────────────────

st.markdown('<p class="main-header">🚁 Skylark Drones BI Agent</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Ask founder-level questions about your deal pipeline and work orders. Data fetched live from Monday.com.</p>', unsafe_allow_html=True)

# ─────────────────────────────────────────
# SAMPLE QUESTIONS (first visit)
# ─────────────────────────────────────────

if len(st.session_state.messages) == 0:
    st.markdown("#### 💡 Try asking:")
    cols = st.columns(3)
    sample_questions = [
        "How's our mining pipeline?",
        "Show open deals with high probability",
        "What's our total receivable amount?",
        "Which sectors have completed work orders?",
        "What's the total value of won deals?",
        "How many deals are on hold?",
    ]
    for i, q in enumerate(sample_questions):
        with cols[i % 3]:
            if st.button(q, key=f"sample_{i}", use_container_width=True):
                st.session_state["prefill_question"] = q
                st.rerun()

    st.markdown("---")

# ─────────────────────────────────────────
# CHAT HISTORY DISPLAY
# ─────────────────────────────────────────

for i, message in enumerate(st.session_state.messages):
    if message["role"] == "user":
        st.markdown(
            f'<div class="user-message">🧑‍💼 <strong>You:</strong> {message["content"]}</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="agent-message">🤖 <strong>Agent:</strong><br>{message["content"]}</div>',
            unsafe_allow_html=True
        )

        # Show trace in expander
        if "trace" in message:
            with st.expander("🔍 Show API Trace", expanded=False):
                st.code(message["trace"], language="text")

        # Show quality caveats if any
        if "caveats" in message and message["caveats"]:
            with st.expander("⚠️ Data Quality Notes", expanded=False):
                st.markdown('<div class="caveat-box">', unsafe_allow_html=True)
                for caveat in message["caveats"][:8]:
                    st.markdown(f"• {caveat}")
                st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────
# INPUT AREA
# ─────────────────────────────────────────

st.markdown("---")

# Handle prefilled question from sample buttons
prefill = st.session_state.pop("prefill_question", "")

col1, col2 = st.columns([5, 1])

with col1:
    user_question = st.text_input(
        "Ask a question:",
        value=prefill,
        placeholder="e.g. Show me mining deals in open status with their values...",
        label_visibility="collapsed",
        key="question_input"
    )

with col2:
    ask_button = st.button("Ask 🚀", use_container_width=True, type="primary")

# ─────────────────────────────────────────
# PROCESS QUESTION
# ─────────────────────────────────────────

if ask_button and user_question.strip():

    # Add user message to history immediately
    st.session_state.messages.append({
        "role": "user",
        "content": user_question.strip()
    })

    with st.spinner("🔄 Fetching live data from Monday.com and analyzing..."):
        try:
            total_start = time.time()

            # ── STEP 1 & 2: Fetch + Normalize ──
            deals_df, orders_df, quality_issues, trace_info = fetch_and_normalize_all()

            # ── STEP 3: Build chat history context (last 4 messages) ──
            recent = st.session_state.messages[-5:-1]  # exclude current question
            chat_history = "\n".join([
                f"{'Founder' if m['role'] == 'user' else 'Agent'}: {m['content'][:150]}"
                for m in recent
            ])

            # ── STEP 4: Generate answer ──
            llm_start = time.time()
            answer = generate_answer(
                question=user_question.strip(),
                deals_df=deals_df,
                orders_df=orders_df,
                chat_history=chat_history,
                quality_issues=quality_issues
            )
            llm_time = round(time.time() - llm_start, 2)
            trace_info["llm_time"] = llm_time

            # ── STEP 5: Create trace ──
            trace = create_trace(
                trace_info=trace_info,
                quality_issues_count=len(quality_issues),
                question=user_question.strip()
            )

            # ── Add agent response to history ──
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "trace": trace,
                "caveats": quality_issues[:8]
            })

            st.session_state.total_queries += 1

        except Exception as e:
            error_msg = str(e)
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"⚠️ Sorry, I ran into an error: `{error_msg}`\n\nPlease check your API keys in `.streamlit/secrets.toml` and try again.",
                "trace": f"ERROR: {error_msg}",
                "caveats": []
            })

    st.rerun()

# ─────────────────────────────────────────
# EMPTY STATE HINT
# ─────────────────────────────────────────

elif ask_button and not user_question.strip():
    st.warning("Please type a question first!")

# ─────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────

st.markdown("---")
st.caption("Built for Skylark Drones · Powered by Groq Llama 3.3 70B · Data from Monday.com (live)")