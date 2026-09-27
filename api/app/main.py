"""海缆故障定位 API。

POST /api/locate  提交树网 + 传感器到时区间，返回所有可行管段、
                  各段里程范围与可共同成立的故障发生时刻范围。
GET  /health      健康检查。
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .model import ApiError, parse_request
from .solver import Tree, first_infeasible_prefix, locate

app = FastAPI(title="海缆故障定位 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def rat(x: Fraction) -> dict:
    """有理数序列化：exact 为精确值（整数或 p/q），approx 为 6 位小数近似。"""
    exact = str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"
    q = (Decimal(x.numerator) / Decimal(x.denominator)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    approx = format(q, "f")
    if "." in approx:
        approx = approx.rstrip("0").rstrip(".")
    if approx in ("-0", ""):
        approx = "0"
    return {"exact": exact, "approx": approx}


def error_response(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400, content={"ok": False, "error": {"code": code, "message": message}}
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/locate")
async def locate_endpoint(request: Request):
    raw = await request.body()
    try:
        payload = json.loads(
            raw.decode("utf-8") if raw else "null",
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error_response("BAD_JSON", "请求体不是合法的 JSON。")

    try:
        problem = parse_request(payload)
    except ApiError as exc:
        return error_response(exc.code, exc.message)

    tree = Tree(problem.nodes, problem.edges)
    segments = locate(tree, problem.sensors, problem.speed)

    if not segments:
        idx = first_infeasible_prefix(tree, problem.sensors, problem.speed)
        assert idx is not None  # 全集不可行，前缀中必有首条使交集为空的记录
        culprit = problem.sensors[idx]
        return {
            "ok": True,
            "feasible": False,
            "culprit": {
                "index": idx,
                "order": idx + 1,
                "id": culprit.sid,
                "node": culprit.node,
                "arrival": {"lo": rat(culprit.lo), "hi": rat(culprit.hi)},
            },
            "message": (
                f"不存在能同时解释全部到时的故障位置与发生时刻。"
                f"按录入顺序逐条加入记录时，第 {idx + 1} 条传感器记录"
                f"（{culprit.sid} @ {culprit.node}）加入后交集首次为空。"
            ),
        }

    return {
        "ok": True,
        "feasible": True,
        "segmentCount": len(segments),
        "segments": [
            {
                "edgeIndex": seg.edge_index,
                "edge": {"from": seg.u, "to": seg.v, "length": rat(seg.length)},
                "fromStart": {"lo": rat(seg.s_lo), "hi": rat(seg.s_hi)},
                "fromEnd": {
                    "lo": rat(seg.length - seg.s_hi),
                    "hi": rat(seg.length - seg.s_lo),
                },
                "occurrenceTime": {"lo": rat(seg.t_lo), "hi": rat(seg.t_hi)},
            }
            for seg in segments
        ],
    }
