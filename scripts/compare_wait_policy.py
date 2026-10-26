"""Re-run saved wait-policy fixtures and compare them on identical request traces."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.dynamic_simulation import generate_requests, run_dynamic_comparison

BASELINE = ROOT / "results" / "wait-aware-forecast-baseline-2026.json"
OUTPUT = ROOT / "results" / "wait-aware-forecast-comparison-2026.json"


def trace_hash(seed: int, bursts: bool, multiplier: float) -> str:
    trace = generate_requests(seed, burst=bursts, traffic_multiplier=multiplier)
    content = json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    baselines = json.loads(BASELINE.read_text(encoding="utf-8"))
    comparisons = []
    for old in baselines:
        payload = old["payload"]
        current = run_dynamic_comparison(payload)
        multiplier = current["traffic_multiplier"] or 1.0
        actual_hash = trace_hash(payload["seed"], payload.get("bursts", True), multiplier)
        if actual_hash != old["request_trace_sha256"]:
            raise RuntimeError(f"Request trace changed for {old['case']}: {actual_hash}")
        comparisons.append({
            "case": old["case"],
            "payload": payload,
            "request_trace_sha256": actual_hash,
            "generated_requests": current["requests_generated"],
            "offered_peak_gpus": current["offered_peak_gpus"],
            "peak_snapshot": current["realized_peak_snapshot"],
            "before": old["policies"],
            "after": {
                name: {
                    "metrics": policy["metrics"],
                    "flexible_admission_status": policy["flexible_admission_status"],
                    "flexible_deadline_misses": policy["metrics"]["flexible_deadline_misses"],
                    "state_at_realized_peak": {
                        "active": current["realized_peak_snapshot"]["active_nodes"],
                        "warm_ready": current["realized_peak_snapshot"]["warm_ready_nodes"],
                        "booting": current["realized_peak_snapshot"]["booting_nodes"],
                        "warming": current["realized_peak_snapshot"]["warming_nodes"],
                        "off": current["realized_peak_snapshot"]["off_nodes"],
                    } if name == "forecast" else None,
                }
                for name, policy in current["policies"].items()
            },
        })
    low_payload = {"seed": 2026, "nodes": 48, "headroom_nodes": 16,
                   "gpus_per_node": 8, "traffic_profile": "low", "bursts": False,
                   "warm_overhead_nodes": 1, "min_active_fraction": 0.5}
    low_run = run_dynamic_comparison(low_payload)
    low_trace_hash = trace_hash(2026, False, low_run["traffic_multiplier"])
    artifact = {
        "comparison_cases": comparisons,
        "profile_examples": [{
            "case": "low-ample-2026",
            "payload": low_payload,
            "request_trace_sha256": low_trace_hash,
            "generated_requests": low_run["requests_generated"],
            "offered_peak_gpus": low_run["offered_peak_gpus"],
            "peak_snapshot": low_run["realized_peak_snapshot"],
            "policies": {name: policy["metrics"] for name, policy in low_run["policies"].items()},
        }],
    }
    OUTPUT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
