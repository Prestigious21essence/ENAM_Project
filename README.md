# FINN — Financial Investment Agent

A mobile-first investor app that filters corporate filings and end-of-day market data for a
portfolio down to the few things that matter.

**Push side (built):** a *morning brief* — the 1–3 events that matter as full cards (results
with QoQ/YoY, leadership changes with bios), the rest as one-line rows, routine paperwork
collapsed. Price/volume alerts are linked to the filings that preceded them.

## How it works

```
NSE (BSE fallback) filings ──> classify (rules, then cheap LLM) ──> cards (results, management)
Yahoo EOD prices ─────────────────────────────────────────────┐            │
                                                              v            v
                                           events (grouped + judged) ──> digest ──> API ──> phone
```

- `backend/refresh.py` — the daily job, end to end (prices → filings → classify → cards → events).
- `backend/api.py` — FastAPI: `/digest`, `/alerts`, `/settings`, `/event/{id}`, `/health/sources`.
- `backend/ingest/screener.py` — screener.in tables (quarterly, P&L, balance sheet, cash flow,
  ratios) and document links (annual reports, concall transcripts/PPTs) for any NSE ticker;
  raw HTML cached one fetch per ticker per day. `push/results_check.py` cross-checks every
  results card's revenue and PAT against screener's quarterly table (flags > 2% off).
- `backend/pull/financials.py` — pull side, no LLM: snapshot, trajectory (CAGR), balance sheet
  and cash-quality sections for any ticker, every number with its screener table/row/column,
  one rule-based takeaway per section; bank/NBFC variant.
- `frontend/` — React + Tailwind (Vite). Screens: Today, Alerts, Settings, event detail.
- Models: Gemini Flash (cheap) with a fallback list; a model whose daily free quota runs out is
  skipped for the rest of the run, and text calls fall back to Mistral's free tier as a last
  resort (image reads of PDF pages stay on Gemini). Every LLM answer is cached on disk and
  logged to `backend/data/cost_log.csv`. Numbers (QoQ, YoY, EBITDA) are computed in Python.

## Run locally

```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
echo GEMINI_API_KEY=your_key > .env
echo FALLBACK_API_KEY=your_mistral_key >> .env   # optional: text-only fallback when Gemini's daily quota is gone
python refresh.py                  # ~10 min cold (Gemini rate limits), seconds when cached
uvicorn api:app --reload           # http://127.0.0.1:8000

cd ../frontend
npm install
npm run dev                        # http://localhost:5173
```

## Deploy

- **Backend:** Render, from `render.yaml` (free plan). The database `backend/data/finn.db` is
  refreshed on a laptop and committed, because NSE may block cloud IPs and the free disk is
  reset on each deploy. `GET /health/sources` shows whether NSE/BSE are reachable from the server.
- **Frontend:** Vercel, root directory `frontend`, env `VITE_API_URL=<Render URL>`.
