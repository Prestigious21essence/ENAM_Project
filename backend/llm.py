"""One place to call the LLM.

call_llm(prompt):
  1. looks in the disk cache (key = sha256 of the prompt) -> free if found
  2. otherwise tries the Gemini Flash models in order (newest ones often 503)
     - a model that hits its DAILY free quota (429 "per day") is marked "out"
       for the rest of this run and is not asked again
  3. if every Gemini model failed and the call has no images, asks the
     second provider (Mistral free tier, OpenAI-compatible API) as the last fallback
     (a caller can also name a Mistral model in `models`, e.g. "mistral-large-latest",
     and it is routed there in that position; skipped when no FALLBACK_API_KEY)
  4. saves the answer to the cache and writes one line to the cost log

.env keys:
  GEMINI_API_KEY      required
  FALLBACK_API_KEY    optional: the second provider's key (Mistral by default)
  FALLBACK_BASE_URL   optional, default https://api.mistral.ai/v1
  FALLBACK_MODEL      optional, default mistral-small-latest
  FINN_DISABLE_GEMINI set to 1 to skip Gemini entirely (forced-fallback test)
"""
import csv
import hashlib
import json
import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache", "llm")
COST_LOG_PATH = os.path.join(DATA_DIR, "cost_log.csv")

# Checked 2026-11-10: 2.5-flash is gone (404); 3.8-flash failed every call
# (503 busy / 504 timeout), so the reliable 3.5-flash goes first.
MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]

# Second provider (text only). Mistral's free "Experiment" plan takes long prompts
# (checked 2026-11-13: ~25k-token prompt accepted). Any OpenAI-compatible
# chat endpoint works here if the three FALLBACK_* keys are changed.
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "https://api.mistral.ai/v1")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "mistral-small-latest")

# Models whose daily quota ran out during this run: don't ask them again.
MODELS_OUT = set()

_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(
                timeout=120000,                                     # milliseconds
                retry_options=types.HttpRetryOptions(attempts=1),   # fail fast, try next model
            ),
        )
    return _client


def gemini_disabled():
    return os.getenv("FINN_DISABLE_GEMINI", "") == "1"


def fallback_available():
    return bool(os.getenv("FALLBACK_API_KEY"))


def is_daily_quota_error(error):
    """True for Gemini's 429 when the free DAILY quota is used up.
    A per-minute 429 says 'PerMinute' / 'per minute' and clears by itself;
    the daily one says 'PerDay' / 'per day' and won't clear until midnight (Pacific)."""
    text = str(error).lower()
    if "429" not in text and "resource_exhausted" not in text:
        return False
    return "perday" in text or "per day" in text


def log_cost(model, input_tokens, output_tokens, purpose):
    is_new_file = not os.path.exists(COST_LOG_PATH)
    with open(COST_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(["time", "model", "input_tokens", "output_tokens", "purpose"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model,
                         input_tokens, output_tokens, purpose])


def call_gemini(model, contents, config):
    """One Gemini call. Returns (text, input_tokens, output_tokens)."""
    response = get_client().models.generate_content(
        model=model, contents=contents, config=config)
    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count or 0
    # "thinking" tokens are billed as output too
    output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return response.text, input_tokens, output_tokens


def is_fallback_model(model):
    """Model names that live on the second provider (e.g. "mistral-large-latest")."""
    return not model.startswith("gemini")


def call_fallback(prompt, json_output, temperature, model=None):
    """One call to the second provider (OpenAI-compatible chat API, text only).
    model: a name on that provider (default FALLBACK_MODEL). Returns (text, input_tokens, output_tokens)."""
    body = {
        "model": model or FALLBACK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_output:
        body["response_format"] = {"type": "json_object"}
    if temperature is not None:
        body["temperature"] = temperature
    response = requests.post(
        FALLBACK_BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + os.getenv("FALLBACK_API_KEY"),
                 "Content-Type": "application/json"},
        json=body, timeout=180)
    if response.status_code != 200:
        raise RuntimeError("fallback " + str(response.status_code) + ": " + response.text[:200])
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def answer_model(prompt, images=None, models=None):
    """Which model wrote the cached answer to this prompt (None if not cached)."""
    key_text = prompt
    if models is not None:
        key_text = key_text + "|models=" + ",".join(models)
    if images:
        for image in images:
            key_text = key_text + hashlib.sha256(image).hexdigest()
    path = os.path.join(CACHE_DIR, hashlib.sha256(key_text.encode("utf-8")).hexdigest() + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("model")


def call_llm(prompt, json_output=False, purpose="", images=None, temperature=None, models=None):
    """Return the model's text answer for this prompt (cached).
    images: optional list of PNG bytes (e.g. a rendered PDF page).
    temperature: 0 for classification (same input -> same answer); None = model default.
    models: optional own order of models to try (default MODELS)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key_text = prompt
    if models is None:
        models = MODELS
    else:
        # an explicit model choice is part of the question (lets a caller re-ask another model)
        key_text = key_text + "|models=" + ",".join(models)
    if images:
        for image in images:
            key_text = key_text + hashlib.sha256(image).hexdigest()
    key = hashlib.sha256(key_text.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, key + ".json")

    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        log_cost("cache", 0, 0, purpose)
        return cached["response"]

    # Bulk extraction doesn't need deep reasoning: keep "thinking" low to save tokens.
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )
    if json_output:
        config.response_mime_type = "application/json"
    if temperature is not None:
        config.temperature = temperature

    contents = []
    if images:
        for image in images:
            contents.append(types.Part.from_bytes(data=image, mime_type="image/png"))
    contents.append(prompt)

    last_error = None
    answer = None
    # Try every model in order that still has quota; if ALL are busy (happens at
    # peak times), wait 20 s and go round once more. Gemini models marked "out"
    # (daily quota used up) are skipped, so a dead model costs nothing more today.
    # A non-Gemini name (e.g. "mistral-large-latest") is routed to the second
    # provider, text-only, and only when its key is set.
    for round_number in range(2):
        available = []
        for model in models:
            if is_fallback_model(model):
                if fallback_available() and not images:
                    available.append(model)
            elif model not in MODELS_OUT and not gemini_disabled():
                available.append(model)
        if len(available) == 0:
            break
        if round_number == 1:
            print("  all models busy, waiting 20 s and trying again...")
            time.sleep(20)
        for model in available:
            try:
                if is_fallback_model(model):
                    text, input_tokens, output_tokens = call_fallback(prompt, json_output, temperature, model)
                else:
                    text, input_tokens, output_tokens = call_gemini(model, contents, config)
                answer = (model, text, input_tokens, output_tokens)
                break
            except Exception as e:
                print("  LLM", model, "failed:", str(e)[:80])
                last_error = e
                if is_daily_quota_error(e):
                    print("  ", model, "daily quota used up: out for the rest of this run")
                    MODELS_OUT.add(model)
        if answer is not None:
            break

    # Last resort for text-only calls: the second provider.
    if answer is None and not images and fallback_available():
        try:
            text, input_tokens, output_tokens = call_fallback(prompt, json_output, temperature)
            answer = (FALLBACK_MODEL, text, input_tokens, output_tokens)
        except Exception as e:
            print("  LLM fallback", FALLBACK_MODEL, "failed:", str(e)[:80])
            last_error = e

    if answer is None:
        reason = "Last error: " + str(last_error)[:200]
        if last_error is None:
            reason = "every model is out (daily quota) and there is no FALLBACK_API_KEY"
        raise RuntimeError("All LLM models failed. " + reason)

    model, text, input_tokens, output_tokens = answer
    log_cost(model, input_tokens, output_tokens, purpose)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"model": model, "prompt": prompt, "response": text}, f)
    return text


if __name__ == "__main__":
    print(call_llm("Reply with exactly: FINN is alive", purpose="test"))
    print(call_llm("Reply with exactly: FINN is alive", purpose="test"))   # 2nd time: from cache
    print(open(COST_LOG_PATH).read())
