"""Stdlib HTTP API for the cable-fault locator (no external dependencies).

Endpoints
---------
``GET  /health``      liveness probe
``POST /api/locate``  exact joint solve over the tree network
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .rational import rat_json
from .solver import LocateError, SolveResult, solve

MAX_BODY_BYTES = 256 * 1024


def _interval_json(lo, hi) -> dict:
    return {"start": rat_json(lo), "end": rat_json(hi)}


def result_to_json(result: SolveResult) -> dict:
    segments = []
    for seg in result.segments:
        segments.append(
            {
                "edge_index": seg.edge_index,
                "u": seg.u,
                "v": seg.v,
                "edge_length": rat_json(seg.length),
                "position_from_u": _interval_json(seg.p_lo, seg.p_hi),
                "mileage": _interval_json(seg.mileage_lo, seg.mileage_hi),
                "occurrence_time": _interval_json(seg.t_lo, seg.t_hi),
                "includes_u": seg.p_lo == 0,
                "includes_v": seg.p_hi == seg.length,
            }
        )
    return {
        "ok": True,
        "speed": rat_json(result.speed),
        "segment_count": len(segments),
        "segments": segments,
        "occurrence_time": _interval_json(result.t_lo, result.t_hi),
    }


def error_payload(exc: LocateError) -> dict:
    return {"ok": False, "error": {"code": exc.code, "message": exc.message, **exc.extra}}


class Handler(BaseHTTPRequestHandler):
    server_version = "CableLocator/1.0"
    protocol_version = "HTTP/1.1"

    # -- helpers -------------------------------------------------------
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: N802 - stdlib hook
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- routes --------------------------------------------------------
    def do_GET(self):  # noqa: N802 - stdlib hook
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "cable-locator-api"})
        else:
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {"code": "NOT_FOUND", "message": f"未知路径: {self.path}"},
                },
            )

    def do_OPTIONS(self):  # noqa: N802 - stdlib hook
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802 - stdlib hook
        if self.path != "/api/locate":
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {"code": "NOT_FOUND", "message": f"未知路径: {self.path}"},
                },
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {
                        "code": "INVALID_BODY",
                        "message": "请求体缺失或超过大小限制",
                    },
                },
            )
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": {"code": "INVALID_BODY", "message": "请求体不是合法 JSON"},
                },
            )
            return
        try:
            result = solve(payload)
        except LocateError as exc:
            status = 422 if exc.code == "NO_FEASIBLE_POSITION" else 400
            self._send_json(status, error_payload(exc))
            return
        except Exception:  # defensive: never leak a bare traceback
            traceback.print_exc()
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": {"code": "INTERNAL", "message": "服务内部错误"},
                },
            )
            return
        self._send_json(200, result_to_json(result))


def main() -> None:
    port = int(os.environ.get("API_PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"cable-locator api listening on :{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
