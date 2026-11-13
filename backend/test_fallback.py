"""M1 check (b): with Gemini switched off, the second provider answers, and its free
tier accepts a ~25k-token prompt (the pull side sends whole concall transcripts).

Needs FALLBACK_API_KEY in backend/.env (see llm.py).
Usage:  python test_fallback.py
"""
import os
import sys
import time

os.environ["FINN_DISABLE_GEMINI"] = "1"       # must be set before llm is imported
sys.path.append(os.path.dirname(__file__))
import llm  # noqa: E402

if not llm.fallback_available():
    print("FALLBACK_API_KEY is not set in backend/.env: nothing to test")
    sys.exit(1)

print("fallback:", llm.FALLBACK_BASE_URL, llm.FALLBACK_MODEL)

# 1. a small call through call_llm itself (Gemini off -> must come from the fallback)
nonce = str(int(time.time()))
answer = llm.call_llm("Reply with exactly: FINN fallback alive " + nonce, purpose="test_fallback")
print("small call ->", answer.strip()[:60])

# 2. ~25k-token prompt: a fake transcript of ~100k characters with one planted fact
line = "The management reiterated its guidance of double-digit revenue growth for the full year. "
pages = []
for i in range(1, 200):
    pages.append("[page " + str(i) + "] " + line * 6)
pages[150] = ("[page 151] The CFO said capex for FY27 will be Rs 4,250 crore, up from Rs 3,100 crore. "
              + line * 5)
prompt = ("Answer only from the transcript below. What capex figure for FY27 did the CFO give, "
          "and on which page? Answer in one line.\n\n" + "\n".join(pages) + "\nnonce " + nonce)
print("prompt:", len(prompt), "chars (~" + str(len(prompt) // 4) + " tokens)")
started = time.time()
text, input_tokens, output_tokens = llm.call_fallback(prompt, json_output=False, temperature=0)
print("big call ->", text.strip()[:120])
print("usage: input", input_tokens, "output", output_tokens, "tokens | took",
      round(time.time() - started, 1), "s")
print("PASS" if "4,250" in text or "4250" in text else "FAIL: planted fact not found")
