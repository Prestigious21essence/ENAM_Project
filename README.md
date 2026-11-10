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
- `frontend/` — React + Tailwind (Vite). Screens: Today, Alerts, Settings, event detail.
- Models: Gemini Flash (cheap) with a fallback list; every LLM answer is cached on disk and
  logged to `backend/data/cost_log.csv`. Numbers (QoQ, YoY, EBITDA) are computed in Python.

## Run locally

```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
echo GEMINI_API_KEY=your_key > .env
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
