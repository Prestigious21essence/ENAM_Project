# AI build history

How FINN was built (8–15 Nov 2026): **Claude Code** (Anthropic's CLI, in this repo) wrote, ran,
tested and debugged all the code and kept `PROGRESS_LOG.md` after every step. Separate
**Claude chats** were used to plan each step and to review/audit its output against the brief
and the source documents (filings, transcripts, screener); their findings and the resulting
decisions are recorded entry by entry in `PROGRESS_LOG.md`. **Antigravity (Gemini)** handled GitHub (repo creation,
pushes). Shubhankur ran the loop, made the decisions, and deployed to Render and Vercel. The
rules are in `WORKFLOW.md`; the plan in `FINN_ROADMAP.md`; what happened, when, and what went
wrong in `PROGRESS_LOG.md`.

## Files

| File | What it is |
|---|---|
| `claude-code/2026-11-10_finn-setup-steps-1-4_a4393ad8.md` | Claude Code session: Steps 1–8, API and mobile app, results-card self-checks (10–11 Nov) |
| `claude-code/2026-11-13_github-code-push_b7b6c547.md` | Claude Code session: preparing the GitHub push |
| `claude-code/2026-11-13_frozen-snapshot-bug-and-deployment_05a76425.md` | Claude Code session: snapshot-date fix, waking-up banner, deploy prep |
| `claude-code/2026-11-13_task-m1-quota-handling-and-provider-fall_e0dc6a84.md` | Claude Code session: M1–M10, M9b–M9d, F1 (13–15 Nov): LLM resilience, screener, numbers, transcripts, guidance, promised-vs-delivered, research API and tab, story stage, robustness, the audit fixes |
| `OTHER_AI_TOOLS.md` | The AI tools used besides Claude Code, and where their work is recorded |
| `PROGRESS_LOG.md` | The running log: every step, what was tried, what failed, the reviews and audits |
| `FINN_ROADMAP.md` | The plan: 19 steps, then the micro-task table with "done when" checks |
| `WORKFLOW.md` | Who does what, the review loop, the GitHub do/don't list |
| `audit_research_reviewer.py` | Read-only audit script: numbers vs screener cells, quotes vs cached PDF pages, verdict consistency, evidence inside the target period, transcript recency |
| `export_sessions.py` | The exporter that turned Claude Code's session files into the markdown above, redacting keys before writing |

The session exports keep every prompt and reply and show each tool call as one line (outputs
omitted, thinking omitted). Secrets were redacted at export time and the folder was checked
afterwards: the real API key appears nowhere in it.
