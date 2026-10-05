"""Run eval/cases.yaml against the real model through the same core function as the endpoint.

    python eval/run_eval.py                       # model from GEMINI_MODEL or the default
    python eval/run_eval.py --model gemini-3.8-flash --runs 3 --delay 6
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.llm import LLMError  # noqa: E402
from app.main import create_parser, process_order  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.yaml"


def compare(case: dict, actual: dict) -> list[str]:
    """Return a list of differences between expected and actual; empty list = pass."""
    problems = []

    expected_items = case.get("items", {})
    actual_items = {i["id"]: i["quantity"] for i in actual["items"]}
    if expected_items != actual_items:
        problems.append(f"items: expected {expected_items}, got {actual_items}")

    remaining = list(actual["unavailable"])
    for e in case.get("unavailable", []):
        forms = [f.lower() for f in e["text"]]
        match = next((a for a in remaining
                      if a["text"].lower() in forms and a["quantity"] == e["quantity"]), None)
        if match:
            remaining.remove(match)
        else:
            problems.append(f"unavailable: missing {e['text'][0]} x{e['quantity']}")
    if remaining:
        problems.append(f"unavailable: unexpected {remaining}")

    def clarifications(entries):
        return sorted((c["quantity"], sorted(c["options"])) for c in entries)

    if clarifications(case.get("needs_clarification", [])) != clarifications(actual["needs_clarification"]):
        problems.append(f"needs_clarification: expected {case.get('needs_clarification', [])}, "
                        f"got {actual['needs_clarification']}")

    if set(case.get("suggestions", [])) != set(actual["suggestions"]):
        problems.append(f"suggestions: expected {sorted(case.get('suggestions', []))}, "
                        f"got {sorted(actual['suggestions'])}")
    return problems


def is_substitution(case: dict, actual: dict) -> bool:
    """The worst error: something off-menu or ambiguous ended up as a menu item (wrong food arrives).
    Detected as: the case expects unavailable/clarification, and the output has a menu item
    (or quantity) that was not expected."""
    if not case.get("unavailable") and not case.get("needs_clarification"):
        return False
    expected_items = case.get("items", {})
    return any(i["quantity"] > expected_items.get(i["id"], 0) for i in actual["items"])


def run_case(parser, text: str, max_rate_limit_waits: int = 3) -> dict:
    for _ in range(max_rate_limit_waits + 1):
        try:
            return process_order(text, parser)
        except LLMError as e:
            if e.code != "llm_rate_limited":
                raise
            print("  rate limited, waiting 60 s...", flush=True)
            time.sleep(60)
    raise LLMError("llm_rate_limited", 503, "still rate limited")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[round(p * (len(ordered) - 1))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="overrides GEMINI_MODEL")
    ap.add_argument("--runs", type=int, default=1, help="repeat every case N times to measure stability")
    ap.add_argument("--delay", type=float, default=6.0, help="seconds between requests (free-tier RPM)")
    ap.add_argument("--category", help="only run this category")
    ap.add_argument("--out", help="write raw results as JSON to this file")
    args = ap.parse_args()

    if args.model:
        os.environ["GEMINI_MODEL"] = args.model
    parser = create_parser()
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]

    results = []
    for run in range(1, args.runs + 1):
        for n, case in enumerate(cases, 1):
            started = time.perf_counter()
            try:
                actual = run_case(parser, case["text"])
                problems = compare(case, actual)
                substitution = is_substitution(case, actual)
            except LLMError as e:
                actual, problems, substitution = None, [f"error: {e.code}"], False
            latency = time.perf_counter() - started
            results.append({"run": run, "category": case["category"], "text": case["text"],
                            "passed": not problems, "problems": problems, "substitution": substitution,
                            "latency_s": round(latency, 3), "actual": actual})
            mark = "PASS" if not problems else "FAIL"
            print(f"[run {run} {n}/{len(cases)}] {mark} {latency:5.2f}s  {case['text']}", flush=True)
            time.sleep(args.delay)

    report(parser.model, args.runs, results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def report(model: str, runs: int, results: list[dict]):
    print(f"\n## Model: {model}, runs: {runs}, cases: {len(results) // runs}\n")
    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r["passed"])
    print("| category | passed |")
    print("|---|---|")
    for category, passed in by_category.items():
        print(f"| {category} | {sum(passed)}/{len(passed)} |")
    total = sum(r["passed"] for r in results)
    print(f"| **total** | **{total}/{len(results)} ({100 * total / len(results):.0f}%)** |")

    substitutions = [r for r in results if r["substitution"]]
    print(f"\nSUBSTITUTIONS (off-menu/ambiguous mapped to a menu item): {len(substitutions)}")
    for r in substitutions:
        print(f"  - [run {r['run']}] {r['text']} -> items {r['actual']['items']}")

    latencies = [r["latency_s"] for r in results if r["actual"] is not None]
    if latencies:
        print(f"\nLatency: p50 {percentile(latencies, 0.5):.2f}s, p95 {percentile(latencies, 0.95):.2f}s")

    if runs > 1:
        outcomes = defaultdict(set)
        for r in results:
            outcomes[r["text"]].add(r["passed"])
        flaky = [text for text, o in outcomes.items() if len(o) > 1]
        print(f"Unstable cases (pass in some runs, fail in others): {len(flaky)}")
        for text in flaky:
            print(f"  - {text}")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print("\nFailures:")
    for r in failures:
        print(f"  - [run {r['run']}] ({r['category']}) {r['text']}")
        for p in r["problems"]:
            print(f"      {p}")


if __name__ == "__main__":
    main()
