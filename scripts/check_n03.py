#!/usr/bin/env python3
"""Compare run_plan(3) with examples/by_terminal_count/n03.json (JSONC)."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from demo_terminal_counts import run_plan  # noqa: E402

rep, resp, req = run_plan(3)
print("Run result:")
print(json.dumps(rep, indent=2, ensure_ascii=False))
print()
print(f"nodes={len(req.nodes)} terminals={len(req.terminals)}")
print(f"backbone edges={len(resp.steiner_tree.edges)} connectors={len(resp.connectors)}")
print()

raw = (ROOT / "examples" / "by_terminal_count" / "n03.json").read_text(encoding="utf-8")
stripped = re.sub(r"//.*", "", raw)
file_data = json.loads(stripped)

keys = [
    "n_terminals",
    "layout",
    "segment_spacing_m",
    "half_span_m",
    "zigzag_amplitude_m",
    "backbone_length_m",
    "total_length_m",
    "connectors",
    "warnings",
    "steiner_points",
    "backbone_edges",
]
print("Compare n03.json (unchanged on disk):")
all_ok = True
for k in keys:
    a, b = file_data.get(k), rep.get(k)
    if isinstance(a, float) and isinstance(b, float):
        ok = abs(a - b) < 0.01
    else:
        ok = a == b
    if not ok:
        all_ok = False
    mark = "OK" if ok else f"MISMATCH  file={a!r}  run={b!r}"
    print(f"  {k}: {mark}")
print()
print("ALL OK" if all_ok else "SOME MISMATCHES")
