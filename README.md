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
- `backend/api.py` — FastAPI: `/digest`, `/alerts`, `/settings`, `/event/{id}`, `/health/sources`,
  and `/research/{ticker}` (pull side: the first call returns the numbers in about a second and
  builds the transcript, guidance and scorecard stages in a background thread; later calls return
  what is ready; finished research is served from `finn.db`; when the daily LLM quota is gone the
  LLM stages report `waiting_quota` instead of failing). `pull/research.py` holds the stages.
- `backend/ingest/screener.py` — screener.in tables (quarterly, P&L, balance sheet, cash flow,
  ratios) and document links (annual reports, concall transcripts/PPTs) for any NSE ticker;
  raw HTML cached one fetch per ticker per day. `push/results_check.py` cross-checks every
  results card's revenue and PAT against screener's quarterly table (flags > 2% off).
- `backend/pull/financials.py` — pull side, no LLM: snapshot, trajectory (CAGR), balance sheet
  and cash-quality sections for any ticker, every number with its screener table/row/column,
  one rule-based takeaway per section; bank/NBFC variant.
- `backend/pull/docs.py` — the last 4–5 concall transcripts per ticker (screener links, NSE
  filings as fallback), text per page cached by URL; the real quarter is read from the text.
- `backend/pull/guidance.py` — management's forward guidance per transcript (cheap model,
  one call per call); every quote is verified verbatim against the cited page in Python or dropped.
- `backend/pull/promises.py` — promised vs delivered: promises grouped into threads with the
  target's movement (reiterated / raised / lowered / dropped), actuals from later transcripts
  (company definitions, verified quotes) or screener where definitions match, Python decides
  whether the period is over and compares, the stronger model writes one cited verdict per
  thread, and a scorecard with a rule-based credibility line.
- `backend/pull/snapshot.py` — the "story" stage: a business snapshot (max 5 bullets) from the latest
  investor presentation, else the latest call's opening remarks, else the annual report, each bullet
  with a verbatim quote verified in Python; and a bull-vs-bear case built only from FINN's own
  evidence (numbers, verdicts, transcript quotes), where the model may point at evidence, not add to it.
- `frontend/` — React + Tailwind (Vite). Screens: Today, Alerts, Research (any NSE symbol:
  promised-vs-delivered scorecard with tappable citations, numbers cards with an inline SVG
  sparkline, sources; builds progressively), Settings, event detail (links to Research).
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
