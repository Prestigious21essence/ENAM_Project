# FINN — AI build history

Every AI conversation used to build FINN. The Claude Code sessions are exported as markdown in
`claude-code/` (prompts, replies, one line per tool call; tool outputs omitted; secrets redacted).
The chats below are shared links.

## Reviewer chat (Claude, "ENAM AI Prompt" project)

The reviewer read `PROGRESS_LOG.md` and the code after each step, gave a verdict and wrote the next
short prompt for Claude Code. It wrote no project code.

| Date | What it covered | Link |
|---|---|---|
| 2026-11-08 → 11-10 | Understanding the brief, roadmap, progress log, first build prompts | _paste share link_ |
| 2026-11-10 → 11-11 | Reviews of Steps 1–4, 5–6, 7–8; API + frontend prompt | _paste share link_ |
| 2026-11-13 | WORKFLOW.md, code review (snapshot bug, waking banner), micro-task plan | _paste share link_ |
| 2026-11-14 → 11-15 | Reviews of M1–M7, re-plan for Sunday, F1/F2 prompts | _paste share link_ |

## Antigravity / Gemini chats (GitHub operations)

Created the private repo and pushed the local commits; reported back to the reviewer.

| Date | What it covered | Link |
|---|---|---|
| 2026-11-13 | Repo creation, `.gitignore` additions, first push (`b2d260c`) | _paste share link_ |
| 2026-11-14 | Pushes of `092bd53` and `fe71567` (Render redeploys) | _paste share link_ |
| 2026-11-15 | Push of M3–M7 commits | _paste share link_ |

## Claude Code sessions (`claude-code/`)

| File | Covered |
|---|---|
| `2026-11-10_finn-setup-steps-1-4_a4393ad8.md` | Steps 1–8, API + mobile app, card self-checks (10–11 Nov) |
| `2026-11-13_github-code-push_b7b6c547.md` | GitHub push preparation |
| `2026-11-13_frozen-snapshot-bug-and-deployment_05a76425.md` | Prompt A: snapshot fix, waking banner |
| `2026-11-13_task-m1-quota-handling-and-provider-fall_e0dc6a84.md` | M1–M7: LLM resilience, screener, numbers, transcripts, guidance, promises, research API (13–15 Nov); exported while still in progress, re-export before submission |

Re-export (from a Claude Code session, no secrets are written): convert each `*.jsonl` under
`%USERPROFILE%\.claude\projects\C--Users-Lenovo-OneDrive-Documents-ENAM-AI\` with the F1 export
script, which redacts keys before writing.
