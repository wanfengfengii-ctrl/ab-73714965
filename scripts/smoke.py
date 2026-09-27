#!/usr/bin/env python3
"""定位 API 冒烟测试。

直连 API 服务做功能冒烟，再经 Web 服务代理验证整条链路。
通过环境变量 API_BASE / WEB_BASE 指定服务地址（Compose 内默认为
http://api:8000 与 http://web）。全部通过时退出码为 0，否则为 1。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
WEB = os.environ.get("WEB_BASE", "http://localhost:8080").rstrip("/")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def http_json(method: str, url: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode() or "null")
        except Exception:
            body = None
        return exc.code, body
    except OSError as exc:
        return None, {"error": str(exc)}


def http_text(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except OSError as exc:
        return None, str(exc)


STAR = {
    "nodes": ["N0", "N1", "N2", "N3", "N4", "N5"],
    "edges": [
        {"from": "N0", "to": n, "length": "1000"} for n in ["N1", "N2", "N3", "N4", "N5"]
    ],
    "speed": "1000",
    "sensors": [
        {"id": "SA", "node": "N1", "arrival": ["11.3", "11.5"]},
        {"id": "SB", "node": "N2", "arrival": ["11.3", "11.5"]},
        {"id": "SC", "node": "N3", "arrival": ["11.3", "11.5"]},
    ],
}

INFEASIBLE = {
    "nodes": ["N1", "N2", "N3", "N4"],
    "edges": [
        {"from": "N1", "to": "N2", "length": "1000"},
        {"from": "N2", "to": "N3", "length": "1000"},
        {"from": "N3", "to": "N4", "length": "1000"},
    ],
    "speed": "1000",
    "sensors": [
        {"id": "SA", "node": "N1", "arrival": ["0", "1"]},
        {"id": "SB", "node": "N4", "arrival": ["0", "1"]},
        {"id": "SC", "node": "N2", "arrival": ["100", "101"]},
    ],
}


def main() -> int:
    print(f"API_BASE={API}  WEB_BASE={WEB}")

    # 1. API 健康检查
    status, body = http_json("GET", f"{API}/health")
    check("api /health", status == 200 and body.get("status") == "ok", f"status={status}")

    # 2. 星形网：应报告 5 段待检区段（而不是一处单点）
    status, body = http_json("POST", f"{API}/api/locate", STAR)
    ok = (
        status == 200
        and body.get("ok") is True
        and body.get("feasible") is True
        and body.get("segmentCount") == 5
    )
    check("api locate 星形网返回 5 段", ok, f"status={status} body={json.dumps(body)[:200]}")
    if ok:
        seg = next(s for s in body["segments"] if s["edge"]["to"] == "N1")
        check(
            "api 里程/时刻范围精确",
            seg["fromStart"]["hi"]["exact"] == "100"
            and seg["occurrenceTime"]["lo"]["exact"] == "103/10",
            json.dumps(seg),
        )

    # 3. 到时区间倒置 -> 400 + 可识别原因
    bad = json.loads(json.dumps(STAR))
    bad["sensors"][0]["arrival"] = ["11.5", "11.3"]
    status, body = http_json("POST", f"{API}/api/locate", bad)
    check(
        "api 区间倒置被拒绝",
        status == 400 and body.get("error", {}).get("code") == "INVALID_INTERVAL",
        f"status={status}",
    )

    # 4. 非树输入 -> 400
    bad = json.loads(json.dumps(STAR))
    bad["edges"] = bad["edges"][:3]
    status, body = http_json("POST", f"{API}/api/locate", bad)
    check(
        "api 非树输入被拒绝",
        status == 400 and body.get("error", {}).get("code") == "NOT_A_TREE",
        f"status={status}",
    )

    # 5. 无可行位置 -> 稳定指出首条使交集为空的记录
    status, body = http_json("POST", f"{API}/api/locate", INFEASIBLE)
    check(
        "api 空交集指出首条记录",
        status == 200
        and body.get("feasible") is False
        and body.get("culprit", {}).get("id") == "SC",
        f"status={status} body={json.dumps(body)[:200]}",
    )

    # 6. Web 健康检查与页面
    status, _ = http_text(f"{WEB}/healthz")
    check("web /healthz", status == 200, f"status={status}")
    status, text = http_text(f"{WEB}/")
    check("web 首页可访问", status == 200 and "海缆故障定位" in text, f"status={status}")

    # 7. 经 Web 代理调用定位 API（端到端链路）
    status, body = http_json("POST", f"{WEB}/api/locate", STAR)
    check(
        "web 代理 /api/locate",
        status == 200 and body.get("feasible") is True and body.get("segmentCount") == 5,
        f"status={status}",
    )

    if failures:
        print(f"\nSMOKE FAILED: {len(failures)} 项未通过 -> {failures}")
        return 1
    print("\nSMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
