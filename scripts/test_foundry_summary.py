#!/usr/bin/env python3
"""
Local diagnostic script to verify Foundry generates summaries.

Run: python scripts/test_foundry_summary.py

Prerequisites:
- Foundry must be running at FOUNDRY_BASE_URL (e.g. http://127.0.0.1:56077/v1)
- Start Foundry locally before running this script
"""
import json
import os
import sys

# Load .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=False)

from pr_agent.config import load_config
from pr_agent.summarizer.foundry_client import FoundryClient
from pr_agent.summarizer.prompts import build_final_prompt, FINAL_SCHEMA


def main() -> None:
    print("=== Foundry Summary Diagnostic ===\n")
    try:
        config = load_config()
        print(f"FOUNDRY_BASE_URL: {config.foundry_base_url}")
        print(f"FOUNDRY_MODEL: {config.foundry_model}\n")
    except Exception as e:
        print(f"Config error: {e}")
        return

    foundry = FoundryClient(config)
    
    # 1. Minimal connectivity test
    print("1. Testing Foundry connectivity (minimal prompt)...")
    try:
        minimal = {"messages": [{"role": "user", "content": "Reply with exactly: {\"ok\": true}"}]}
        out = foundry.chat_json(minimal)
        print(f"   Response: {json.dumps(out, indent=2)[:300]}")
        print("   OK\n")
    except Exception as e:
        print(f"   FAILED: {e}")
        print("\n   >>> Foundry is NOT reachable. Start Foundry first, then retry.")
        print(f"   >>> URL: {config.foundry_base_url}\n")
        return

    # 2. Test final summary schema (simulated PR)
    print("2. Testing full summary generation (simulated PR)...")
    pr_title = "Add login validation"
    pr_body = "Adds input validation to the login handler."
    file_summaries = [
        {"file_path": "auth.py", "what_changed": "Added validation", "summary": ["Validation added"], "intent": "Security"}
    ]
    full_diff = "--- auth.py ---\n+def validate_input(x):\n+    return x.strip()"

    prompt = build_final_prompt(pr_title, pr_body, file_summaries, full_diff=full_diff)
    print(f"   Prompt has {len(prompt['messages'])} messages, ~{sum(len(str(m)) for m in prompt['messages'])} chars\n")

    try:
        summary = foundry.chat_json(prompt)
        print(f"   Raw response type: {type(summary)}")
        print(f"   Raw response:\n{json.dumps(summary, indent=2)[:1500]}...\n")

        if isinstance(summary, dict):
            has_summary = "summary" in summary and summary.get("summary")
            print(f"   Has 'summary' key: {has_summary}")
            if has_summary:
                s = summary["summary"]
                print(f"   summary value type: {type(s)}")
                if isinstance(s, list):
                    print(f"   summary list length: {len(s)}")
                    for i, item in enumerate(s[:3]):
                        print(f"     [{i}]: {repr(item)[:80]}")
            else:
                print("   WARNING: Model did not return 'summary' - UI will show 'No summary yet'")
        else:
            print("   WARNING: Response is not a dict")
    except Exception as e:
        print(f"   FAILED: {e}")
        import traceback
        traceback.print_exc()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
