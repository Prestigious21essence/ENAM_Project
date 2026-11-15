"""Export Claude Code session .jsonl files to readable, REDACTED markdown.

Usage: python export_sessions.py <projects dir for this project> <output dir>

Kept:   the user's prompts, Claude's replies (text), tool calls as one line each.
Dropped: tool outputs (only their size is noted), thinking, system reminders, API request blobs.
Redacted before writing: API keys (AIza..., sk-..., ghp_..., Bearer ...), any KEY=value line,
.env-style assignments, and anything that looks like a long secret token.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

SECRET_PATTERNS = [
    re.compile(r"AIza\S*"),                                                   # Google / Gemini keys (and any mention of their prefix)
    re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"),                                  # OpenAI-style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                              # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.=]{16,}"),                       # Authorization headers
    re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z0-9_]*)\s*[=:]\s*['\"]?[^\s'\"<>\[\]`\)]{6,}"),
    re.compile(r"(?i)x-api-key\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9]{32}\b(?=.*(?i:mistral|key|token))"),           # 32-char keys when the line talks about keys
]


def redact(text):
    if not text:
        return text
    def keep_name(m):
        # for NAME=value keep the name, hide the value
        if m.lastindex:
            return m.group(1) + "=[REDACTED]"
        return "[REDACTED]"
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(keep_name, text)
    # personal e-mail addresses (the public ENAM submission address is kept)
    def email(m):
        return m.group(0) if m.group(0).lower() == "assessment@enam.com" else "[email redacted]"
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", email, text)
    return text


def strip_harness(text):
    """Remove <system-reminder> blocks and the pasted_content wrapper tags from a user prompt."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = re.sub(r"</?pasted_content[^>]*>", "", text)
    return text.strip()


def ist(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
    except (TypeError, ValueError):
        return None


def tool_line(block):
    name = block.get("name", "tool")
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return "- 🔧 " + name
    if name in ("Read", "Write", "Edit", "MultiEdit"):
        detail = inp.get("file_path", "")
    elif name in ("PowerShell", "Bash"):
        detail = str(inp.get("command", "")).strip().splitlines()[0] if inp.get("command") else ""
        detail = detail[:140]
    elif name in ("Grep", "Glob"):
        detail = str(inp.get("pattern", ""))[:100] + (("  in " + inp["path"]) if inp.get("path") else "")
    elif name == "WebSearch":
        detail = str(inp.get("query", ""))[:120]
    elif name.startswith("mcp__ccd_turn__update_plan"):
        items = inp.get("items")
        detail = ("plan: " + "; ".join(i.get("content", "") for i in items)) if items else "advance"
    elif name.startswith("mcp__ccd_turn__wrap_up"):
        detail = str(inp.get("recap", ""))[:160]
    else:
        detail = json.dumps(inp, ensure_ascii=False)[:120]
    return "- 🔧 **" + name.replace("mcp__", "") + "** " + redact(detail).replace("\n", " ")


def export(path, out_dir):
    records = []
    title = None
    cost = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            t = rec.get("type")
            if t == "custom-title":
                title = rec.get("customTitle")
            elif t == "cost-state":
                cost = rec
            elif t in ("user", "assistant"):
                records.append(rec)
    if not records:
        return None

    first = None
    last = None
    for r in records:
        d = ist(r.get("timestamp"))
        if d:
            first = first or d
            last = d
    session_id = os.path.basename(path).replace(".jsonl", "")
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "session").lower()).strip("-")[:40]
    out_name = (first.strftime("%Y-%m-%d") if first else "undated") + "_" + slug + "_" + session_id[:8] + ".md"

    lines = ["# Claude Code session: " + (title or session_id), ""]
    lines.append("- **Session id:** `" + session_id + "`")
    if first:
        lines.append("- **Started:** " + first.strftime("%Y-%m-%d %H:%M IST") + "  ·  **last message:** " + last.strftime("%Y-%m-%d %H:%M IST"))
    if cost:
        lines.append("- **Model usage:** " + ", ".join(sorted((cost.get("modelUsage") or {}).keys())) + "  ·  lines added/removed: "
                     + str(cost.get("totalLinesAdded")) + "/" + str(cost.get("totalLinesRemoved")))
    lines.append("- **Export:** tool outputs omitted (size noted), thinking omitted, secrets redacted as `[REDACTED]`.")
    lines.append("")

    pending_tool_results = {}
    for r in records:
        msg = r.get("message") or {}
        content = msg.get("content")
        when = ist(r.get("timestamp"))
        stamp = when.strftime("%H:%M") if when else ""
        if r["type"] == "user":
            if isinstance(content, str):
                text = strip_harness(content)
                if text:
                    lines.append("\n## 🧑 Shubhankur  `" + stamp + "`\n")
                    lines.append(redact(text))
            elif isinstance(content, list):
                texts = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        texts.append(strip_harness(b.get("text", "")))
                    elif b.get("type") == "tool_result":
                        body = b.get("content")
                        if isinstance(body, list):
                            body = " ".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in body)
                        size = len(str(body or ""))
                        flag = " ⚠️ error" if b.get("is_error") else ""
                        lines.append("  - ↳ result: " + str(size) + " chars" + flag)
                text = "\n\n".join(t for t in texts if t)
                if text:
                    lines.append("\n## 🧑 Shubhankur  `" + stamp + "`\n")
                    lines.append(redact(text))
        else:  # assistant
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    lines.append("\n## 🤖 Claude  `" + stamp + "`\n")
                    lines.append(redact(b["text"].strip()))
                elif b.get("type") == "tool_use":
                    lines.append(tool_line(b))
    text = "\n".join(lines) + "\n"
    text = redact(text)   # belt and braces: the whole document once more
    out_path = os.path.join(out_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(src, "*.jsonl")), key=os.path.getmtime):
        result = export(path, out)
        if result:
            print(round(os.path.getsize(result) / 1024), "KB", os.path.basename(result), "<-", os.path.basename(path))
