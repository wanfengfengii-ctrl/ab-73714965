"""HTTP API tests: routing, status codes, exact JSON payloads."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from api.app.server import Handler


def y_payload(s3_window=("5/2", "11/2")):
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
            {"id": "S3", "node": 3, "start": s3_window[0], "end": s3_window[1]},
        ],
    }


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        data = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_locate_ok_exact_payload(self):
        status, body = self._post("/api/locate", y_payload())
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["segment_count"], 3)
        by_edge = {(s["u"], s["v"]): s for s in body["segments"]}
        self.assertEqual(set(by_edge), {(1, 2), (2, 3), (2, 4)})

        trunk = by_edge[(1, 2)]
        self.assertEqual(trunk["position_from_u"]["start"]["exact"], "7/2")
        self.assertEqual(trunk["position_from_u"]["end"]["exact"], "4")
        self.assertEqual(trunk["mileage"]["start"]["exact"], "7/2")
        self.assertEqual(trunk["occurrence_time"]["start"]["exact"], "1/2")
        self.assertEqual(trunk["occurrence_time"]["end"]["exact"], "3/2")
        self.assertTrue(trunk["includes_v"])
        self.assertFalse(trunk["includes_u"])

        arm_a = by_edge[(2, 3)]
        self.assertEqual(arm_a["position_from_u"]["start"]["exact"], "0")
        self.assertEqual(arm_a["position_from_u"]["end"]["exact"], "3/2")
        self.assertEqual(arm_a["mileage"]["end"]["exact"], "11/2")
        self.assertEqual(arm_a["occurrence_time"]["start"]["exact"], "-1/2")
        self.assertTrue(arm_a["includes_u"])

        arm_b = by_edge[(2, 4)]
        self.assertEqual(arm_b["position_from_u"]["start"]["exact"], "0")
        self.assertEqual(arm_b["position_from_u"]["end"]["exact"], "4")
        self.assertEqual(arm_b["mileage"]["end"]["exact"], "8")
        self.assertEqual(arm_b["occurrence_time"]["start"]["exact"], "-7/2")
        self.assertTrue(arm_b["includes_u"])
        self.assertTrue(arm_b["includes_v"])

        self.assertEqual(body["occurrence_time"]["start"]["exact"], "-7/2")
        self.assertEqual(body["occurrence_time"]["end"]["exact"], "3/2")

    def test_validation_error_400(self):
        payload = y_payload()
        payload["sensors"][0]["start"], payload["sensors"][0]["end"] = "9", "8"
        status, body = self._post("/api/locate", payload)
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "INTERVAL_INVERTED")
        self.assertIn("S1", body["error"]["message"])

    def test_no_feasible_422_with_first_empty_sensor(self):
        status, body = self._post("/api/locate", y_payload(s3_window=("20", "21")))
        self.assertEqual(status, 422)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "NO_FEASIBLE_POSITION")
        self.assertEqual(body["error"]["first_empty_sensor"], "S3")
        self.assertEqual(body["error"]["sensor_index"], 3)

    def test_bad_json_400(self):
        status, body = self._post("/api/locate", None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_BODY")

    def test_unknown_routes_404(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)
        status, _ = self._post("/nope", y_payload())
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
