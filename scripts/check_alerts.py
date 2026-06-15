"""Evaluate the alert rules in config/alert_rules.yaml against the live /metrics snapshot.

Usage:
    python scripts/check_alerts.py
    python scripts/check_alerts.py --base-url http://127.0.0.1:8000 --rules config/alert_rules.yaml

Exit code is 0 when no alert is firing, 1 when one or more alerts are firing
(handy for CI / `&&` chaining). Metrics with no underlying samples are treated
as "no data" and never fire, so an empty system does not page anyone.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
import yaml

RULES_PATH = "config/alert_rules.yaml"
BASE_URL = "http://127.0.0.1:8000"

COMPARATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def load_rules(path: str | Path = RULES_PATH) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("alerts", [])


def fetch_metrics(base_url: str = BASE_URL) -> dict:
    resp = httpx.get(f"{base_url}/metrics", timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def derive_metrics(snapshot: dict) -> dict:
    """Map the raw /metrics snapshot onto the metric names used by alert rules.

    `error_rate_pct` is derived from the error counts vs total handled requests.
    Sample-dependent metrics are set to None when there were no successful
    requests, so they read as "no data" instead of firing on zeros.
    """
    errors = snapshot.get("error_breakdown", {}) or {}
    total_errors = sum(errors.values())
    traffic = snapshot.get("traffic", 0)
    handled = traffic + total_errors
    error_rate_pct = round(total_errors / handled * 100, 2) if handled else 0.0
    have_samples = traffic > 0

    return {
        "traffic": traffic,
        "total_errors": total_errors,
        "error_rate_pct": error_rate_pct,
        "latency_p50_ms": snapshot.get("latency_p50", 0.0) if have_samples else None,
        "latency_p95_ms": snapshot.get("latency_p95", 0.0) if have_samples else None,
        "latency_p99_ms": snapshot.get("latency_p99", 0.0) if have_samples else None,
        "avg_cost_usd": snapshot.get("avg_cost_usd", 0.0) if have_samples else None,
        "total_cost_usd": snapshot.get("total_cost_usd", 0.0),
        "tokens_in_total": snapshot.get("tokens_in_total", 0),
        "tokens_out_total": snapshot.get("tokens_out_total", 0),
        "quality_avg": snapshot.get("quality_avg", 0.0) if have_samples else None,
    }


def evaluate(rules: list[dict], values: dict) -> list[dict]:
    results = []
    for rule in rules:
        metric = rule["metric"]
        comparator = rule["comparator"]
        threshold = rule["threshold"]
        value = values.get(metric)
        compare = COMPARATORS.get(comparator)
        firing = value is not None and compare is not None and compare(value, threshold)
        results.append(
            {
                "name": rule["name"],
                "severity": rule.get("severity", "?"),
                "metric": metric,
                "comparator": comparator,
                "threshold": threshold,
                "value": value,
                "firing": firing,
            }
        )
    return results


def _fmt(value) -> str:
    if value is None:
        return "no-data"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def print_report(results: list[dict]) -> None:
    print("--- Alert Evaluation ---")
    header = f"{'STATUS':<8} {'SEVERITY':<8} {'ALERT':<22} CONDITION (value vs threshold)"
    print(header)
    print("-" * len(header))
    for r in results:
        status = "FIRING" if r["firing"] else ("OK" if r["value"] is not None else "NO-DATA")
        cond = f"{r['metric']} {r['comparator']} {r['threshold']}  (current={_fmt(r['value'])})"
        print(f"{status:<8} {r['severity']:<8} {r['name']:<22} {cond}")
    firing = [r for r in results if r["firing"]]
    print("-" * len(header))
    if firing:
        print(f"{len(firing)} alert(s) FIRING: " + ", ".join(r["name"] for r in firing))
    else:
        print("No alerts firing.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate alert rules against /metrics.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--rules", default=RULES_PATH)
    args = parser.parse_args()

    rules = load_rules(args.rules)
    try:
        snapshot = fetch_metrics(args.base_url)
    except Exception as exc:  # pragma: no cover - operator feedback
        print(f"Error: could not fetch {args.base_url}/metrics ({exc}). Is the app running?")
        sys.exit(2)

    values = derive_metrics(snapshot)
    results = evaluate(rules, values)
    print_report(results)
    sys.exit(1 if any(r["firing"] for r in results) else 0)


if __name__ == "__main__":
    main()
