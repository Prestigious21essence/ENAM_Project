"""One place to call the LLM.

call_llm(prompt):
  1. looks in the disk cache (key = sha256 of the prompt) -> free if found
  2. otherwise tries the Gemini Flash models in order (newest ones often 503)
  3. saves the answer to the cache and writes one line to the cost log
"""
import csv
import hashlib
import json
import os
import time
from datetime import datetime

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


def log_cost(model, input_tokens, output_tokens, purpose):
    is_new_file = not os.path.exists(COST_LOG_PATH)
    with open(COST_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(["time", "model", "input_tokens", "output_tokens", "purpose"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model,
                         input_tokens, output_tokens, purpose])


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

    # Try every model; if ALL are busy (happens at peak times), wait and go round once more.
    attempts = models + models
    last_error = None
    for attempt_number in range(len(attempts)):
        model = attempts[attempt_number]
        if attempt_number == len(models):
            print("  all models busy, waiting 20 s and trying again...")
            time.sleep(20)
        try:
            response = get_client().models.generate_content(
                model=model, contents=contents, config=config)
        except Exception as e:
            print("  LLM", model, "failed:", str(e)[:80])
            last_error = e
            continue

        text = response.text
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        # "thinking" tokens are billed as output too
        output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        log_cost(model, input_tokens, output_tokens, purpose)

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"model": model, "prompt": prompt, "response": text}, f)
        return text

    raise RuntimeError("All LLM models failed. Last error: " + str(last_error))


if __name__ == "__main__":
    print(call_llm("Reply with exactly: FINN is alive", purpose="test"))
    print(call_llm("Reply with exactly: FINN is alive", purpose="test"))   # 2nd time: from cache
    print(open(COST_LOG_PATH).read())
