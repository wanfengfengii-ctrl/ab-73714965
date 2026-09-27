"""One-shot verification pipeline for the cable-fault locator.

Steps, in order:
  1. wait for the API and Web services to become healthy;
  2. run the unit/integration test suite (code tests);
  3. run the frontend build;
  4. smoke-test the location API end to end (exact expected values,
     validation errors, and the first-empty-sensor explanation).

The process exit code is 0 only if every step passed, so
``docker compose up --exit-code-from verify`` reports the result.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8080").rstrip("/")
WAIT_SECONDS = int(os.environ.get("VERIFY_WAIT_SECONDS", "90"))

RESULTS = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok))
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    return ok


def wait_http(url: str, timeout: int = WAIT_SECONDS) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def post_json(url: str, payload: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def run_unit_tests() -> bool:
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    return result.wasSuccessful()


def run_frontend_build() -> tuple:
    out_dir = Path(os.environ.get("VERIFY_WEB_OUT", "/tmp/web-dist"))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "web" / "build.py"), "--out", str(out_dir)],
        capture_output=True,
        text=True,
    )
    detail = ""
    if proc.stdout:
        detail = proc.stdout.strip().splitlines()[-1]
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else "构建脚本退出码非零"
        return False, detail
    expected = {"index.html", "app.js", "styles.css", "config.js", "health"}
    produced = {p.name for p in out_dir.iterdir()} if out_dir.is_dir() else set()
    if not expected <= produced:
        return False, f"构建产物缺失: {sorted(expected - produced)}"
    return True, detail


def smoke_payload() -> dict:
    return {
        "nodes": [1, 2, 3, 4],
        "edges": [
            {"u": 1, "v": 2, "length": "4"},
            {"u": 2, "v": 3, "length": "4"},
            {"u": 2, "v": 4, "length": "4"},
        ],
        "speed": "1",
        "sensors": [
            {"id": "S1", "node": 1, "start": "9/2", "end": "11/2"},
            {"id": "S2", "node": 2, "start": "1/2", "end": "3/2"},
            {"id": "S3", "node": 3, "start": "5/2", "end": "11/2"},
        ],
    }


def smoke_api() -> tuple:
    """End-to-end checks against the live API; returns (ok, detail)."""
    checks = []

    # 1. Forked-tree echo case: three exact segments expected.
    status, body = post_json(f"{API_URL}/api/locate", smoke_payload())
    ok = status == 200 and body.get("ok") is True
    checks.append(("分叉案例返回 200", ok))
    if not ok:
        return False, f"分叉案例状态异常: {status} {body}"
    expected_segments = {
        (1, 2): ("7/2", "4", "1/2", "3/2"),
        (2, 3): ("0", "3/2", "-1/2", "3/2"),
        (2, 4): ("0", "4", "-7/2", "3/2"),
    }
    got = {}
    for seg in body.get("segments", []):
        got[(seg["u"], seg["v"])] = (
            seg["position_from_u"]["start"]["exact"],
            seg["position_from_u"]["end"]["exact"],
            seg["occurrence_time"]["start"]["exact"],
            seg["occurrence_time"]["end"]["exact"],
        )
    checks.append(("三段待检区段精确匹配", got == expected_segments))
    checks.append((
        "总发生时刻范围精确",
        body.get("occurrence_time", {}).get("start", {}).get("exact") == "-7/2"
        and body.get("occurrence_time", {}).get("end", {}).get("exact") == "3/2",
    ))

    # 2. Validation error: inverted interval must be identifiable.
    bad = smoke_payload()
    bad["sensors"][0]["start"], bad["sensors"][0]["end"] = "9", "8"
    status, body = post_json(f"{API_URL}/api/locate", bad)
    checks.append((
        "区间倒置返回 400/INTERVAL_INVERTED",
        status == 400
        and body.get("error", {}).get("code") == "INTERVAL_INVERTED"
        and "S1" in body.get("error", {}).get("message", ""),
    ))

    # 3. Not a tree.
    bad = smoke_payload()
    bad["edges"] = bad["edges"][:2]
    status, body = post_json(f"{API_URL}/api/locate", bad)
    checks.append((
        "非树输入返回 400/NOT_A_TREE",
        status == 400 and body.get("error", {}).get("code") == "NOT_A_TREE",
    ))

    # 4. No feasible position: stable first-empty-sensor explanation.
    bad = smoke_payload()
    bad["sensors"][2]["start"], bad["sensors"][2]["end"] = "20", "21"
    status, body = post_json(f"{API_URL}/api/locate", bad)
    checks.append((
        "无可行位置返回 422 并指明首条致空记录",
        status == 422
        and body.get("error", {}).get("code") == "NO_FEASIBLE_POSITION"
        and body.get("error", {}).get("first_empty_sensor") == "S3",
    ))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}", flush=True)
    if failed:
        return False, "；".join(failed)
    return True, f"{len(checks)} 项冒烟断言全部通过"


def main() -> int:
    print("== 1/4 等待依赖服务就绪 ==", flush=True)
    record(f"API 健康 ({API_URL}/health)", wait_http(f"{API_URL}/health"))
    record(f"Web 健康 ({WEB_URL}/health)", wait_http(f"{WEB_URL}/health"))

    print("== 2/4 代码测试 ==", flush=True)
    try:
        record("代码测试", run_unit_tests())
    except Exception as exc:  # noqa: BLE001 - report and fail the step
        record("代码测试", False, repr(exc))

    print("== 3/4 前端构建 ==", flush=True)
    try:
        ok, detail = run_frontend_build()
    except SystemExit as exc:
        ok, detail = False, str(exc)
    record("前端构建", ok, detail)

    print("== 4/4 定位 API 冒烟 ==", flush=True)
    if all(ok for _, ok in RESULTS[:2]):
        try:
            ok, detail = smoke_api()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, repr(exc)
        record("定位 API 冒烟", ok, detail)
    else:
        record("定位 API 冒烟", False, "依赖服务未就绪，跳过")

    print("=" * 60, flush=True)
    failed = [name for name, ok in RESULTS if not ok]
    if failed:
        print(f"VERIFY FAILED: {', '.join(failed)}", flush=True)
        return 1
    print("VERIFY OK: 依赖健康、代码测试、前端构建、定位 API 冒烟全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
