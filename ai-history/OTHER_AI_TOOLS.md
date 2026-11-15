# Other AI tools used (besides Claude Code)

- **Claude chats (8–15 Nov):** used to plan each step and to review/audit the output against the
  brief and the source documents (numbers against screener cells, quotes against PDF pages,
  management cards against filings). Their reviews, the bugs they found and the decisions taken
  are recorded entry by entry in `PROGRESS_LOG.md`; the audit script is `audit_research_reviewer.py`.
- **Antigravity (Gemini):** GitHub operations: created the repository and pushed the local commits.
- **Gemini API (3.5-flash, 3.5-flash-lite, 3.6-flash):** the models inside FINN itself; every call
  is cached and logged to `backend/data/cost_log.csv` (not committed).

The Claude Code sessions, which contain every prompt and reply of the build, are in `claude-code/`.
