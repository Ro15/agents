"""
Lightweight NL->SQL evaluation runner.

Usage:
  python scripts/evaluate_nl2sql.py --cases eval_cases.jsonl --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


def _load_cases(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        obj["_line"] = i
        cases.append(obj)
    return cases


def _post_json(url: str, payload: Dict[str, Any], timeout: float) -> tuple[int, Dict[str, Any], float]:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            elapsed_ms = (time.time() - t0) * 1000
            return resp.status, json.loads(body) if body else {}, elapsed_ms
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        elapsed_ms = (time.time() - t0) * 1000
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"detail": body}
        return e.code, parsed, elapsed_ms
    except URLError as e:
        elapsed_ms = (time.time() - t0) * 1000
        return 0, {"detail": str(e)}, elapsed_ms


def _contains_all(haystack: str, needles: List[str]) -> bool:
    h = (haystack or "").lower()
    return all((n or "").lower() in h for n in needles)


def _contains_none(haystack: str, needles: List[str]) -> bool:
    h = (haystack or "").lower()
    return all((n or "").lower() not in h for n in needles)


def evaluate_case(case: Dict[str, Any], base_url: str, timeout: float) -> Dict[str, Any]:
    payload = {
        "query": case["question"],
        "plugin": case["plugin"],
        "dataset_id": case["dataset_id"],
    }
    if case.get("conversation_history"):
        payload["conversation_history"] = case["conversation_history"]

    status, body, elapsed_ms = _post_json(f"{base_url.rstrip('/')}/chat", payload, timeout=timeout)
    sql = body.get("sql") if isinstance(body, dict) else None
    answer_type = body.get("answer_type") if isinstance(body, dict) else None

    sql_must_contain = case.get("sql_must_contain") or []
    sql_must_not_contain = case.get("sql_must_not_contain") or []
    expected_type = case.get("expected_answer_type")

    checks = {
        "http_ok": status == 200,
        "sql_present": bool(sql),
        "answer_type_match": (answer_type == expected_type) if expected_type else True,
        "sql_contains": _contains_all(sql or "", sql_must_contain),
        "sql_not_contains": _contains_none(sql or "", sql_must_not_contain),
    }
    passed = all(checks.values())
    return {
        "line": case.get("_line"),
        "question": case.get("question"),
        "status": status,
        "latency_ms": round(elapsed_ms, 1),
        "checks": checks,
        "passed": passed,
        "sql": sql,
        "answer_type": answer_type,
        "error": body.get("detail") if isinstance(body, dict) else None,
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    p95 = 0.0
    if results:
        latencies = sorted(r["latency_ms"] for r in results)
        idx = min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))
        p95 = latencies[idx]
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round((passed / total) * 100, 1) if total else 0.0,
        "p95_latency_ms": p95,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate NL->SQL quality via /chat endpoint.")
    parser.add_argument("--cases", required=True, help="Path to JSONL cases file")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout seconds")
    parser.add_argument("--output", default="", help="Optional path to write JSON report")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cases = _load_cases(cases_path)
    if not cases:
        print("No test cases found.")
        return 1

    results = [evaluate_case(case, args.base_url, args.timeout) for case in cases]
    summary = summarize(results)
    report = {"summary": summary, "results": results}

    print(json.dumps(summary, indent=2))
    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"\nFailed cases: {len(failed)}")
        for f in failed[:10]:
            print(f"- line {f['line']}: {f['question']} (status={f['status']}, checks={f['checks']})")

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote report to {args.output}")

    return 0 if summary["passed"] == summary["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
