import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "healthcare_data.json"

# Sonnet 5 balances cost and quality for this showcase; override via env var
# for a different model (e.g. claude-haiku-4-5, claude-opus-5). Note: Haiku
# 4.5 and Sonnet 4.5 (not 5) don't support output_config.effort at all -
# src/agent.py detects this automatically and stops sending it after the
# first rejected request.
MODEL_ID = os.environ.get("MARIA_CARE_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.environ.get("MARIA_CARE_MAX_TOKENS", "2048"))

# This is a directory lookup / tool-dispatch agent, not a deep-reasoning task,
# and both channels (phone, chat) are latency-sensitive - keep effort low.
EFFORT = os.environ.get("MARIA_CARE_EFFORT", "low")

# Safety net: force-escalate a turn rather than loop forever if Claude keeps
# calling tools without ever reaching a final answer.
MAX_TOOL_ITERATIONS = int(os.environ.get("MARIA_CARE_MAX_TOOL_ITERATIONS", "4"))

# Cap on stored conversation messages (not tokens) to bound context growth in
# a long-running interactive demo session.
MAX_HISTORY_MESSAGES = int(os.environ.get("MARIA_CARE_MAX_HISTORY_MESSAGES", "20"))
