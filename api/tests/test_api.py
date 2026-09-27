"""API 测试：健康检查、成功定位、各类可识别错误、空交集 culprit。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

STAR_PAYLOAD = {
    "nodes": ["N0", "N1", "N2", "N3", "N4", "N5"],
    "edges": [
        {"from": "N0", "to": "N1", "length": "1000"},
        {"from": "N0", "to": "N2", "length": "1000"},
        {"from": "N0", "to": "N3", "length": "1000"},
        {"from": "N0", "to": "N4", "length": "1000"},
        {"from": "N0", "to": "N5", "length": "1000"},
    ],
    "speed": "1000",
    "sensors": [
        {"id": "SA", "node": "N1", "arrival": ["11.3", "11.5"]},
        {"id": "SB", "node": "N2", "arrival": ["11.3", "11.5"]},
        {"id": "SC", "node": "N3", "arrival": ["11.3", "11.5"]},
    ],
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_locate_star_lists_all_segments():
    resp = client.post("/api/locate", json=STAR_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] and data["feasible"]
    assert data["segmentCount"] == 5
    segs = {s["edge"]["to"]: s for s in data["segments"]}
    # 挂传感器的臂：仅 [0, 100] 米可行
    assert segs["N1"]["fromStart"] == {
        "lo": {"exact": "0", "approx": "0"},
        "hi": {"exact": "100", "approx": "100"},
    }
    # 里程范围两端互补：距 N1 端为 [900, 1000]
    assert segs["N1"]["fromEnd"]["lo"]["exact"] == "900"
    assert segs["N1"]["fromEnd"]["hi"]["exact"] == "1000"
    # 发生时刻范围精确值：10.3 = 103/10
    assert segs["N1"]["occurrenceTime"]["lo"] == {"exact": "103/10", "approx": "10.3"}
    assert segs["N1"]["occurrenceTime"]["hi"] == {"exact": "21/2", "approx": "10.5"}
    # 未挂传感器的臂：整条可行
    assert segs["N4"]["fromStart"]["hi"]["exact"] == "1000"
    assert segs["N4"]["occurrenceTime"]["lo"]["exact"] == "93/10"


def test_numbers_accepted_as_strings_and_numbers():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["edges"][0]["length"] = 1000  # JSON 数字而非字符串
    payload["speed"] = 1000
    payload["sensors"][0]["arrival"] = [11.3, 11.5]  # 浮点按十进制精确解析
    resp = client.post("/api/locate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["segmentCount"] == 5


def _expect_error(payload, code):
    resp = client.post("/api/locate", json=payload)
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == code
    assert data["error"]["message"]
    return data


def test_node_count_out_of_range():
    payload = {**STAR_PAYLOAD, "nodes": ["A", "B", "C"], "edges": STAR_PAYLOAD["edges"][:2]}
    _expect_error(payload, "NODE_COUNT_OUT_OF_RANGE")


def test_not_a_tree_edge_count():
    payload = {**STAR_PAYLOAD, "edges": STAR_PAYLOAD["edges"][:3]}
    data = _expect_error(payload, "NOT_A_TREE")
    assert "4 条边" in data["error"]["message"] or "5 条边" in data["error"]["message"]


def test_not_a_tree_disconnected():
    payload = {
        **STAR_PAYLOAD,
        "nodes": ["A", "B", "C", "D"],
        "edges": [
            {"from": "A", "to": "B", "length": 1},
            {"from": "B", "to": "C", "length": 1},
            {"from": "C", "to": "A", "length": 1},
        ],
    }
    data = _expect_error(payload, "NOT_A_TREE")
    assert "不连通" in data["error"]["message"]


def test_invalid_length():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["edges"][0]["length"] = "0"
    _expect_error(payload, "INVALID_LENGTH")
    payload["edges"][0]["length"] = "-5"
    _expect_error(payload, "INVALID_LENGTH")


def test_invalid_speed():
    payload = {**STAR_PAYLOAD, "speed": "0"}
    _expect_error(payload, "INVALID_SPEED")
    payload = {**STAR_PAYLOAD, "speed": "-1500"}
    _expect_error(payload, "INVALID_SPEED")


def test_duplicate_sensor_node():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["sensors"][1]["node"] = "N1"
    _expect_error(payload, "DUPLICATE_SENSOR")


def test_duplicate_sensor_id():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["sensors"][1]["id"] = "SA"
    _expect_error(payload, "DUPLICATE_SENSOR")


def test_inverted_interval():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["sensors"][0]["arrival"] = ["11.5", "11.3"]
    data = _expect_error(payload, "INVALID_INTERVAL")
    assert "倒置" in data["error"]["message"]


def test_sensor_count_out_of_range():
    payload = {**STAR_PAYLOAD, "sensors": STAR_PAYLOAD["sensors"][:2]}
    _expect_error(payload, "SENSOR_COUNT_OUT_OF_RANGE")


def test_unknown_node():
    import copy

    payload = copy.deepcopy(STAR_PAYLOAD)
    payload["edges"][0]["to"] = "NX"
    _expect_error(payload, "UNKNOWN_NODE")


def test_bad_json():
    resp = client.post(
        "/api/locate", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "BAD_JSON"


def test_infeasible_reports_first_empty_record():
    payload = {
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
    resp = client.post("/api/locate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] and data["feasible"] is False
    assert data["culprit"]["id"] == "SC"
    assert data["culprit"]["index"] == 2
    assert data["culprit"]["order"] == 3
    assert "SC" in data["message"]
