"""
Shared resumability check for the download_*.py scripts.

A chunk is "done" once Breeze gave a definitive answer (HTTP Status 200),
even if Success came back empty -- that's a real, valid "no trades in this
window" (confirmed: deep-ITM/OTM option strikes routinely return
Error=None, Status=200, Success=[] for whole days they didn't trade, same
shape as a market holiday). Treating an empty Success as "not done" would
re-fetch every illiquid strike/holiday forever. Only a missing/corrupt file
or a non-200 response should trigger a retry.
"""

import json
from pathlib import Path


def is_saved(out_path: Path) -> bool:
    if not out_path.exists():
        return False
    try:
        record = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return (record.get("response") or {}).get("Status") == 200
