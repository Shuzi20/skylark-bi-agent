# 🚁 Skylark Drones BI Agent

An AI-powered Business Intelligence agent that answers founder-level queries about deal pipeline and work orders using live Monday.com data.

## Tech Stack

- **UI:** Streamlit
- **AI:** Groq Llama 3.3 70B
- **Data:** Monday.com GraphQL API (live, no cache)
- **Language:** Python 3.9+

## Architecture

```
Founder Question
      ↓
  app.py  (Streamlit UI + session state)
      ↓
data_layer.py  ──────────→  Monday.com API (live GraphQL)
  fetch + normalize
      ↓
intelligence_layer.py  ──→  Groq API (Llama 3.3 70B)
  build context + answer
      ↓
  Display answer + trace
```

## Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/your-username/skylark-bi-agent
cd skylark-bi-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your API keys
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and fill in your keys

# 4. Run
streamlit run app.py
```

## Setup secrets.toml

```toml
MONDAY_API_TOKEN = "your_monday_api_token"
MONDAY_DEALS_BOARD_ID = "your_deals_board_id"
MONDAY_WORK_ORDERS_BOARD_ID = "your_work_orders_board_id"
GROQ_API_KEY = "your_groq_api_key"
```

## Deploy to Streamlit Cloud

1. Push code to GitHub (never commit `secrets.toml`)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click **New app** → select repo → select `app.py`
4. Go to **Settings → Secrets** and paste your keys
5. Deploy — live in ~2 minutes

## Sample Questions

- *How's our mining pipeline?*
- *Show open deals with high probability*
- *What's our total receivable amount?*
- *Which sectors have the most completed work orders?*
- *What's the total value of won deals?*

## Data Quality Handling

| Issue | How Handled |
|-------|-------------|
| 2 duplicate header rows | Filtered out (Deal Status == "Deal Status") |
| 75% null closure probability | Caveated in every answer |
| 52% null deal values | Totals noted as partial |
| 0.0 in financial columns | Treated as missing, not zero |
| Typo: 'BIlled' | Normalized to 'Billed' |
| 8+ execution status variants | Normalized to 5 standard categories |
