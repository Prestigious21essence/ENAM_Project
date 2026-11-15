# FINN — writeup

- **App (open on a phone):** https://enam-project.vercel.app
  *The backend runs on a free server that sleeps when idle. The first load can take up to a minute ("Waking up the server…"); after that it's instant.*
- **Repository:** https://github.com/Prestigious21essence/ENAM_Project (the commit tagged `submission` is what I handed in)
- **AI build history:** `ai-history/` in the repo: every Claude Code session (all prompts and replies) and the step-by-step progress log
- **Try:** Today → tap the top item · Alerts · **Research → TCS** · Research → any NSE symbol you like

## What I built

FINN has one point of view: **an investor should open it, see what changed and whether management can be trusted, and close it in 30 seconds.**

**Push: a morning brief, not a feed.** An 18-company portfolio across 16 sectors. Filings come from NSE (BSE as fallback) and EOD prices from Yahoo. Over 45 days of results season, 349 filings become 140 events: **23 that matter, 49 worth a look, 68 routine ones collapsed into one line**. On a normal day that's about one item. When nothing happened, the brief says so and never pads.
- **Priority is judged per event, not per category.** Results reach the top only if PAT moved ≥ 25% YoY or the stock reacted; a leadership change only if a top person joins or leaves. Price/volume alerts (thresholds set by the user) are linked to the filing that preceded them.
- **Results card:** Revenue / EBITDA / PBT / PAT, QoQ and YoY (banks: NII and pre-provision profit). ITC's revenue is shown net of excise: +3.9%, not the headline +43.9%.
- **Management card:** who joins or leaves, the role, the date and the reason, plus a bio from the filing. If the filing says "details already provided", FINN finds the person in the company's earlier filings.

**Pull: research on any NSE ticker.** 11 companies are pre-built; anything else builds live on the server (numbers in ~2 s, the rest within minutes).
- **Numbers, with no LLM:** snapshot, trajectory, balance sheet and cash quality from screener's tables. Every figure cites its table and column, and the takeaways come from rules.
- **Promised vs delivered** (the core): the last 5 earnings calls → management's explicit guidance → grouped into threads that show **how each target moved** → actuals in the company's own words from later calls → a verdict.
  - *TCS:* margin guidance went 26–28% → "towards 26%" → "exit FY27 at 25%+" → back to 26–28%, while the reported margin fell to 24%. **Behind, with two quiet walk-backs.**
  - *Asian Paints:* an 18–20% margin band reiterated on all 5 calls, then 17.1% in Q2 FY27. The volume guide was trimmed from 8–10% to 8–9%.
- **Business snapshot + bull vs bear:** the model may only point at evidence FINN has already verified; it can't add facts.
- **Every claim is a tappable chip** that opens the verbatim quote, the speaker and the PDF at that page.

## Key decisions and trade-offs

1. **A brief, not a feed or a grid.** A feed hands the filtering back to the investor; a grid answers "how is X?", not "what changed?".
2. **Numbers never come from the LLM.** The model only copies line items from the P&L page (sent as an image, because some filings are scanned). Python does the arithmetic and checks four accounting identities on every reading. All 18 results cards match screener on revenue and PAT for all three periods (108/108 checks).
3. **Grounding is enforced in code, not asked for in a prompt.** Every quote shown is string-matched against its cited PDF page in Python, and anything that doesn't match is dropped. **Python decides every verdict**; the model only writes the sentence. Evidence must fall inside the target's own period, "medium term" is never "missed", and future plans are never counted as results.
4. **Don't trust labels or definitions.** Screener linked a July 2025 call as "Jul 2026", so the quarter is read from the transcript itself. TCS's "operating margin" is EBIT while screener's OPM is EBITDA-based, so actuals use the company's own definition.
5. **I audited my own output.** A separate review pass re-checked everything against the sources: 154 figures, 103 derived ratios, ~240 quotes and all 26 management cards. It caught real errors (a CMD shown as "leaving" when he only gave up an additional charge; promises judged against the wrong year's numbers; 4-year-old calls used for a company with no recent transcripts). Each was fixed with a rule, not a prompt tweak, and the audit script ships in the repo.
6. **Cost: rules first, cheap model for bulk, stronger model only for verdicts, three caches.** The whole build used 332 LLM calls (1.94M input / 118k output tokens): **about US$0.42 at list price, ₹0 actually spent** (free tier). One company's research is ~20 calls, about US$0.02–0.06. Re-runs cost nothing.
7. **Designed for free-tier failure.** Gemini's free quota is per model per day (20/day on the strongest Flash). Exhausted models are skipped for the rest of the run, and research stages show "paused until the quota resets" while the numbers still render. Nothing returns an error page.
8. **Built for a reviewer who opens it days later.** NSE works from the cloud server; BSE is blocked there (403). Filings are refreshed on my laptop and the database ships with the code, and every window is anchored to the data's "as of" time so the app never goes blank.

## What I deliberately left out

- **Web/LinkedIn enrichment for bios:** the filings were enough in every case I tested.
- **Real push notifications (Telegram):** the brief and alerts are in-app.
- **A free-form "Ask" chat:** structured, cited research is far easier to keep grounded than open chat.
- **Annual-report deep dives** (related-party transactions, contingent liabilities, auditor notes): transcripts gave a better signal per token for promised vs delivered.
- **User accounts:** settings are shared by all viewers and reset on redeploy.
- **A second LLM provider:** the fallback code is in place, but Mistral's free plan wouldn't issue an API key, so FINN runs on Gemini's free tier alone.

## Where I'd take it next

- **An alert when a new call quietly lowers a target**, where push meets pull, plus a say-do score per management across years.
- **A portfolio view:** which holdings' managements are slipping on guidance this quarter.
- **Annual-report analytics** with the same verified-quote discipline.
- **A scheduled server-side refresh on a paid model tier**, plus Telegram push for high-priority items.

## How I worked

I built FINN with AI tools, and the decisions on scope, priorities and trade-offs were mine. Claude Code wrote, ran and tested the code. A separate Claude chat helped me plan each step and review its output against the brief and the source documents; that review is where several of the bugs above were caught. Antigravity (Gemini) handled the GitHub pushes. Every step had a "done when" check, with numbers hand-checked against the source PDFs. The Claude Code sessions and the step-by-step progress log, including every review finding, are in `ai-history/`.
