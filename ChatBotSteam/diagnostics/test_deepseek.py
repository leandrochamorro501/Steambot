"""
tests/test_deepseek.py
---------------------
Diagnostic script to verify DeepSeek connectivity and intent extraction.
"""

import sys
import os
import io
# Fix Windows console encoding for special characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("DEEPSEEK DIAGNOSTICS")
print("=" * 60)

# 1. Environment variables
print("\n[1] Environment Variables:")
apikey    = os.getenv("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_APIKEY", ""))
base_url  = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model_id  = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

print(f"  DEEPSEEK_APIKEY:    {'SET' if apikey else 'MISSING'}")
print(f"  DEEPSEEK_BASE_URL:  {base_url}")
print(f"  DEEPSEEK_MODEL_ID:  {model_id}")

if not apikey:
    print("\n  [ERROR] DEEPSEEK_APIKEY is missing. Check your .env file.")
    sys.exit(1)
print("\n  Env vars OK.")

# 2. Client creation
print("\n[2] Testing OpenAI client creation...")
try:
    import openai
    client = openai.OpenAI(api_key=apikey, base_url=base_url)
    print("  Client created OK.")
except Exception as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# 3. Models list
print(f"\n[3] Listing available models...")
try:
    models = client.models.list()
    model_ids = [m.id for m in models.data]
    print(f"  Found {len(model_ids)} model(s): {model_ids[:10]}")
except Exception as e:
    print(f"  [WARNING] Could not list models: {e}")

# 4. Simple chat completion
print(f"\n[4] Testing chat completion with model='{model_id}'...")
try:
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": "Respond with just: HELLO"}],
        max_tokens=64,
        temperature=0.0,
    )
    text = response.choices[0].message.content
    print(f"  Response: {text!r}")
    print("  Chat completion OK!")
except Exception as e:
    print(f"  [ERROR] {e}")
    sys.exit(1)

# 5. Intent extraction
print("\n[5] Testing intent extraction (JSON output)...")
try:
    from core.llm_engine import extract_intent, ConversationMemory
    memory = ConversationMemory()
    intent = extract_intent("Quiero juegos de terror en el espacio", memory)
    print(f"  Extracted intent: {intent}")
    if intent.get("tags") or intent.get("genre"):
        print("  Extraction OK!")
    else:
        print("  [WARNING] No tags/genre extracted — check prompt template")
except Exception as e:
    print(f"  [ERROR] {e}")

# 6. Currency conversion
print("\n[6] Testing currency conversion...")
try:
    from core.currency import convert_usd
    clp = convert_usd(14.99, "CLP")
    ars = convert_usd(14.99, "ARS")
    eur = convert_usd(14.99, "EUR")
    print(f"  $14.99 USD → {clp} (CLP)")
    print(f"  $14.99 USD → {ars} (ARS)")
    print(f"  $14.99 USD → {eur} (EUR)")
    print("  Currency OK!")
except Exception as e:
    print(f"  [ERROR] {e}")

print("\n" + "=" * 60)
print("DIAGNOSTICS COMPLETE")
print("=" * 60)
