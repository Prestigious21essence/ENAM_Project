# FINN — How We Work

> Every tool reads this file and `PROGRESS_LOG.md` before starting.
> This file = the rules. `PROGRESS_LOG.md` = what happened and what's next.

## Who does what
| Who | Role |
|---|---|
| **Shubhankur** | Builder and owner of the project, working solo. Makes all decisions. |
| **Claude Code** (on the laptop, in `finn/`) | Writes, runs, tests and debugs all code. Does the heavy reasoning. Updates `PROGRESS_LOG.md` after every session. |
| **Reviewer chat** (Claude, "ENAM AI Prompt" project) | Reads `PROGRESS_LOG.md` and the code, then reviews against the brief and roadmap. Points out what's wrong and writes the **next short prompt** for Claude Code. Doesn't write project code. |
| **Antigravity / Gemini** | GitHub operations (create the repo, push). Reports results back to the reviewer. |

## The loop
1. Reviewer gives a short prompt, which is pasted into Claude Code.
2. Claude Code does the work, commits locally, updates `PROGRESS_LOG.md` (Current status + a Log entry) and ticks `FINN_ROADMAP.md`.
3. Shubhankur says **"review"** in the reviewer chat.
4. The reviewer reads the log and the code and replies with: a verdict, the issues (only what's wrong), and the next prompt.

## Rules
- **Prompts are short**: a few lines, step-focused. Details live in the roadmap and the log.
- **Reviews are short**: verdict, issues, prompt.
- **Verify, don't assume**: every step has a "Done when" check; show real output; hand-check at least one number against the source PDF.
- **Simple, readable code**: no clever idioms.
- Commit after each step (author: Shubhankur).
- Every AI conversation goes into `finn/ai-history/` (share links / exports). This is a **required submission item**.

## Locations
- Docs: `C:\Users\Lenovo\OneDrive\Documents\ENAM AI\` (this file, `PROGRESS_LOG.md`, `FINN_ROADMAP.md`, brief PDFs)
- Code + git repo: `...\ENAM AI\finn\` (the repo contains only this subfolder)
- **Pause OneDrive syncing while working.** It has already created conflict copies and swallowed an edit.

## GitHub
### Must NOT be pushed (already in `.gitignore`)
`backend/.env` (API key!) · `.venv/` · `node_modules/` · `dist/` · `__pycache__/` · `backend/data/cache/` (250 MB) · `cost_log*.csv` · OneDrive `*Name clash*` / `*Edit conflict*` files · also add `.env.*` and `.vercel/`

### MUST be pushed
All code · `backend/data/finn.db` (the deployed backend serves from it) · `portfolio.json` · `ai-history/` · `README.md`

### Push steps (Antigravity / Gemini runs these in `finn/`)
1. On github.com, create a **private** repo named `finn`, with **no** README, license or .gitignore.
2. Add `.env.*` and `.vercel/` to `.gitignore` and commit.
3. Run `git status` and `git ls-files`. **Stop** if any "must NOT" file is listed.
4. `git remote add origin https://github.com/<username>/finn.git`
5. `git branch -M main`
6. `git push -u origin main` (Windows opens a browser login the first time)
7. Don't rewrite history, squash or change the author.
8. **Report back to the reviewer:** repo URL, the `git ls-files` output, the push output.
- Before submission: make the repo **public** (or add the ENAM reviewers), then check on github.com that `.env` isn't there.

## Deadline & submission
- **Sun 15 Nov 2026** → assessment@enam.com, subject **"IIT Delhi – AI Engineer - 2027"**
- Send: deployed phone link + GitHub repo + AI build history + short writeup (built / decisions & trade-offs / left out / next).
