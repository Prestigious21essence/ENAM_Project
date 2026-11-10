import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key or api_key == "paste_your_key_here":
    print("GEMINI_API_KEY is missing. Put it in backend/.env")
    raise SystemExit(1)

# Only 1 attempt per model: if a model is busy, move on to the next one
# instead of letting the SDK retry for minutes.
client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(
        timeout=60000,   # milliseconds
        retry_options=types.HttpRetryOptions(attempts=1),
    ),
)

# gemini-2.5-flash is retired for new keys (404).
# The newest flash models often return 503 (high demand), so try a few in order.
MODELS_TO_TRY = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]

for model in MODELS_TO_TRY:
    try:
        response = client.models.generate_content(
            model=model,
            contents="Reply with exactly: FINN is alive",
        )
        print(model, "->", response.text)
        break
    except Exception as e:
        print(model, "failed:", str(e)[:80])
