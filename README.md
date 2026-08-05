# FundGPT - Mutual Fund Analytics Chatbot

A Streamlit chatbot for exploring Indian mutual fund performance and risk
metrics: "top N funds in a category", full fund profiles, and a guided
Asset Type → Sub Category browsing flow.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI (chat, sidebar, guided buttons) |
| `finance_bot.py` | Core logic — data loading, matching, ranking, formatting |
| `llm_fallback.py` | Optional Groq-powered fallback for free-form finance Q&A |
| `MF_Risk_Metrics_1.xlsx` | The fund dataset (sheet: `Risk Metrics`) — must stay in the repo root, alongside `finance_bot.py` |
| `requirements.txt` | Python dependencies |

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## Optional: enable general finance Q&A

Free-text questions that aren't a "top N funds" or "tell me about <fund>"
request (e.g. "what does Sharpe ratio mean?") are answered by an optional
Groq LLM fallback. Without a key, the app still works fully for fund
lookups — it just guides the user via buttons instead.

Get a free key at https://console.groq.com, then either:

- **Local run:** `export GROQ_API_KEY=your_key_here` before `streamlit run app.py`
- **Streamlit Community Cloud:** add it under your app's *Settings → Secrets*:
  ```toml
  GROQ_API_KEY = "your_key_here"
  ```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (see below).
2. Go to https://share.streamlit.io → **New app**.
3. Pick this repo, branch `main`, and set the main file to `app.py`.
4. (Optional) Add `GROQ_API_KEY` under **Advanced settings → Secrets**.
5. Deploy.

> The dataset file is ~8 MB and is committed directly to the repo — well
> under GitHub's 100 MB per-file limit, so no Git LFS is needed.

## Pushing this repo to GitHub

```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

(Create the empty repo on GitHub first, without a README/license, so
there's nothing to conflict with the initial push.)

## Notes

- `finance_bot.py`'s data loader is intentionally fixed to
  `MF_Risk_Metrics_1.xlsx` / sheet `Risk Metrics` in the same folder —
  there's no upload path or alternate-file override.
- Same underlying fund listed under multiple plan-options (Growth, IDCW,
  Dividend, etc.) is automatically de-duplicated in "top funds" results,
  preferring the Growth variant.
