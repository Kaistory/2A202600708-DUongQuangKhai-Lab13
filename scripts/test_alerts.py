"""End-to-end test for the alert rules in config/alert_rules.yaml.

For each scenario it boots a fresh app instance (on its own port, so the
in-memory metrics start clean), optionally injects an incident, drives the
sample load through /chat, then evaluates the alert rules against /metrics and
asserts that exactly the expected alert(s) fired.

Run from the repo root:
    python scripts/test_alerts.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Allow running as `python scripts/test_alerts.py` (scripts/ is on sys.path).
from check_alerts import derive_metrics, evaluate, load_rules

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "data" / "sample_queries.jsonl"

SCENARIOS = [
    {"name": "baseline", "incident": None, "expect": set()},
    {"name": "rag_slow", "incident": "rag_slow", "expect": {"high_latency_p95"}},
    {"name": "cost_spike", "incident": "cost_spike", "expect": {"cost_budget_spike"}},
    {"name": "tool_fail", "incident": "tool_fail", "expect": {"high_error_rate"}},
]


def terminate_tree(proc: subprocess.Popen) -> None:
    """Kill the app process *and its children*.

    uvicorn's startup spawns a multiprocessing helper that inherits the
    listening socket; a plain terminate() of the parent orphans it and leaks the
    port. On Windows `taskkill /T` reaps the whole tree.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


def wait_for_health(base_url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=2.0).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def drive_load(base_url: str) -> None:
    with httpx.Client(timeout=60.0) as client:
        for line in QUERIES.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                client.post(f"{base_url}/chat", json=json.loads(line))
            except Exception:
                pass  # 500s are expected (e.g. tool_fail); they are recorded as errors


def run_scenario(scenario: dict, port: int, rules: list[dict]) -> dict:
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_health(base_url):
            raise RuntimeError(f"app did not become healthy on port {port}")
        if scenario["incident"]:
            httpx.post(f"{base_url}/incidents/{scenario['incident']}/enable", timeout=10.0)
        drive_load(base_url)
        snapshot = httpx.get(f"{base_url}/metrics", timeout=10.0).json()
    finally:
        terminate_tree(proc)

    results = evaluate(rules, derive_metrics(snapshot))
    firing = {r["name"] for r in results if r["firing"]}
    return {"snapshot": snapshot, "results": results, "firing": firing}


def main() -> None:
    rules = load_rules(ROOT / "config" / "alert_rules.yaml")
    print(f"Loaded {len(rules)} alert rules from config/alert_rules.yaml\n")

    all_pass = True
    for i, scenario in enumerate(SCENARIOS):
        port = 8001 + i
        print(f"=== Scenario: {scenario['name']}  (incident={scenario['incident'] or 'none'}, port={port}) ===")
        outcome = run_scenario(scenario, port, rules)
        firing = outcome["firing"]
        expect = scenario["expect"]
        ok = firing == expect

        for r in outcome["results"]:
            val = r["value"]
            val_s = "no-data" if val is None else (f"{val:.4f}".rstrip("0").rstrip(".") if isinstance(val, float) else str(val))
            mark = "FIRING" if r["firing"] else "  ok  "
            print(f"   [{mark}] {r['name']:<22} {r['metric']} {r['comparator']} {r['threshold']} (current={val_s})")
        verdict = "PASS" if ok else "FAIL"
        print(f"   -> expected={sorted(expect) or '[]'}  fired={sorted(firing) or '[]'}  [{verdict}]\n")
        all_pass = all_pass and ok

    print("=" * 60)
    print("RESULT:", "ALL SCENARIOS PASSED" if all_pass else "SOME SCENARIOS FAILED")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
