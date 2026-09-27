"""Unit tests for the exact continuous solver."""
from __future__ import annotations

import unittest
from fractions import Fraction as F

from api.app.solver import LocateError, solve


def line_payload(lengths=("2", "3", "2"), windows=None, speed="1"):
    """4-node line 1-2-3-4 with sensors at 1, 4, 2."""
    if windows is None:
        windows = [("5/2", "7/2"), ("7/2", "9/2"), ("1/2", "3/2")]
    return {
        "nodes": [1, 2, 3, 4],
        "edges": [
            {"u": 1, "v": 2, "length": lengths[0]},
            {"u": 2, "v": 3, "length": lengths[1]},
            {"u": 3, "v": 4, "length": lengths[2]},
        ],
        "speed": speed,
        "sensors": [
            {"id": "S1", "node": 1, "start": windows[0][0], "end": windows[0][1]},
            {"id": "S2", "node": 4, "start": windows[1][0], "end": windows[1][1]},
            {"id": "S3", "node": 2, "start": windows[2][0], "end": windows[2][1]},
        ],
    }


def y_payload(s3_window=("5/2", "11/2")):
    """Y-shaped tree: trunk 1-2 plus arms 2-3 and 2-4, all length 4.

    Sensors sit at nodes 1, 2, 3; arm 2-4 carries no sensor.  The windows
    are consistent with a fault near the junction on any of the three
    cable sections - the records cannot tell them apart.
    """
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


class SolveLineTest(unittest.TestCase):
    def test_single_segment_exact(self):
        result = solve(line_payload())
        self.assertEqual(len(result.segments), 1)
        seg = result.segments[0]
        self.assertEqual((seg.u, seg.v), (2, 3))
        self.assertEqual((seg.p_lo, seg.p_hi), (F(1, 2), F(3, 2)))
        self.assertEqual((seg.mileage_lo, seg.mileage_hi), (F(5, 2), F(7, 2)))
        self.assertEqual((seg.t_lo, seg.t_hi), (F(-1, 2), F(1, 2)))
        self.assertEqual((result.t_lo, result.t_hi), (F(-1, 2), F(1, 2)))

    def test_envelope_extremum_inside_interval(self):
        # Wide windows: tau extrema sit at an interior breakpoint (p = 1),
        # not at the ends of the feasible position range.  The shared node
        # 2 also shows up as a zero-width feasible point on edge (1, 2):
        # closed intervals on adjacent edges both cover their common node.
        result = solve(line_payload(windows=[("2", "4"), ("3", "5"), ("0", "2")]))
        self.assertEqual(len(result.segments), 2)
        by_edge = {(s.u, s.v): s for s in result.segments}
        seg = by_edge[(2, 3)]
        self.assertEqual((seg.p_lo, seg.p_hi), (F(0), F(2)))
        self.assertEqual((seg.t_lo, seg.t_hi), (F(-1), F(1)))
        point = by_edge[(1, 2)]
        self.assertEqual((point.p_lo, point.p_hi), (F(2), F(2)))
        self.assertEqual((point.t_lo, point.t_hi), (F(0), F(0)))
        self.assertEqual((result.t_lo, result.t_hi), (F(-1), F(1)))

    def test_speed_scales_occurrence_time_not_position(self):
        # Doubling the speed while halving the arrival windows leaves the
        # scaled time tau = v*t (hence positions) unchanged, so the
        # occurrence-time range halves exactly.
        slow = solve(line_payload(speed="1"))
        fast = solve(line_payload(speed="2",
                                  windows=[("5/4", "7/4"), ("7/4", "9/4"), ("1/4", "3/4")]))
        self.assertEqual(len(fast.segments), 1)
        self.assertEqual((fast.segments[0].p_lo, fast.segments[0].p_hi),
                         (slow.segments[0].p_lo, slow.segments[0].p_hi))
        self.assertEqual((fast.t_lo, fast.t_hi),
                         (slow.t_lo / 2, slow.t_hi / 2))


class SolveBranchTest(unittest.TestCase):
    def test_same_echo_on_forked_arms_gives_all_segments(self):
        # The headline scenario: one set of records is consistent with a
        # fault on the trunk near the junction, on the instrumented arm,
        # or anywhere on the uninstrumented arm.  All three closed
        # segments must be reported - never a single "nearest sensor"
        # point.
        result = solve(y_payload())
        self.assertEqual(len(result.segments), 3)
        by_edge = {(s.u, s.v): s for s in result.segments}
        self.assertEqual(set(by_edge), {(1, 2), (2, 3), (2, 4)})

        trunk = by_edge[(1, 2)]
        self.assertEqual((trunk.p_lo, trunk.p_hi), (F(7, 2), F(4)))
        self.assertEqual((trunk.mileage_lo, trunk.mileage_hi), (F(7, 2), F(4)))
        self.assertEqual((trunk.t_lo, trunk.t_hi), (F(1, 2), F(3, 2)))

        arm_a = by_edge[(2, 3)]
        self.assertEqual((arm_a.p_lo, arm_a.p_hi), (F(0), F(3, 2)))
        self.assertEqual((arm_a.mileage_lo, arm_a.mileage_hi), (F(4), F(11, 2)))
        self.assertEqual((arm_a.t_lo, arm_a.t_hi), (F(-1, 2), F(3, 2)))

        arm_b = by_edge[(2, 4)]  # no sensor beyond the junction: whole arm
        self.assertEqual((arm_b.p_lo, arm_b.p_hi), (F(0), F(4)))
        self.assertEqual((arm_b.mileage_lo, arm_b.mileage_hi), (F(4), F(8)))
        self.assertEqual((arm_b.t_lo, arm_b.t_hi), (F(-7, 2), F(3, 2)))

        self.assertEqual((result.t_lo, result.t_hi), (F(-7, 2), F(3, 2)))

    def test_exact_point_solution_with_fractions(self):
        # Point windows and third-length edges: exact Fraction arithmetic
        # must pin a single point at p = 1/6, t = 1/6.
        payload = line_payload(
            lengths=("1/3", "1/3", "1/3"),
            windows=[("2/3", "2/3"), ("2/3", "2/3"), ("1/3", "1/3")],
        )
        result = solve(payload)
        self.assertEqual(len(result.segments), 1)
        seg = result.segments[0]
        self.assertEqual((seg.u, seg.v), (2, 3))
        self.assertEqual((seg.p_lo, seg.p_hi), (F(1, 6), F(1, 6)))
        self.assertEqual((seg.t_lo, seg.t_hi), (F(1, 6), F(1, 6)))
        self.assertEqual((seg.mileage_lo, seg.mileage_hi), (F(1, 2), F(1, 2)))

    def test_decimal_strings_are_exact(self):
        # 0.1 must mean exactly 1/10, not the binary float.
        payload = line_payload(
            lengths=("0.3", "0.3", "0.3"),
            windows=[("0.6", "0.7"), ("0.6", "0.7"), ("0.3", "0.4")],
        )
        result = solve(payload)
        self.assertEqual(len(result.segments), 1)
        seg = result.segments[0]
        # p in [1/10, 1/5]: exact tenths, free of binary-float residue.
        self.assertEqual(seg.p_lo, F(1, 10))
        self.assertEqual(seg.p_hi, F(1, 5))

    def test_no_feasible_reports_first_empty_sensor(self):
        with self.assertRaises(LocateError) as ctx:
            solve(y_payload(s3_window=("20", "21")))
        exc = ctx.exception
        self.assertEqual(exc.code, "NO_FEASIBLE_POSITION")
        self.assertEqual(exc.extra["first_empty_sensor"], "S3")
        self.assertEqual(exc.extra["sensor_index"], 3)
        self.assertEqual(exc.extra["considered_sensors"], ["S1", "S2", "S3"])
        self.assertIn("S3", exc.message)

    def test_no_feasible_second_sensor(self):
        # S2 alone already contradicts S1 on every edge.
        payload = y_payload()
        payload["sensors"][1]["start"] = "100"
        payload["sensors"][1]["end"] = "101"
        with self.assertRaises(LocateError) as ctx:
            solve(payload)
        self.assertEqual(ctx.exception.extra["first_empty_sensor"], "S2")
        self.assertEqual(ctx.exception.extra["sensor_index"], 2)


class ValidationTest(unittest.TestCase):
    def assert_code(self, payload, code):
        with self.assertRaises(LocateError) as ctx:
            solve(payload)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)

    def test_not_a_tree_edge_count(self):
        payload = y_payload()
        payload["edges"] = payload["edges"][:2]
        self.assert_code(payload, "NOT_A_TREE")

    def test_not_a_tree_cycle(self):
        payload = {
            "nodes": [1, 2, 3, 4, 5],
            "edges": [
                {"u": 1, "v": 2, "length": "1"},
                {"u": 2, "v": 3, "length": "1"},
                {"u": 3, "v": 1, "length": "1"},
                {"u": 4, "v": 5, "length": "1"},
            ],
            "speed": "1",
            "sensors": [
                {"id": "S1", "node": 1, "start": "0", "end": "1"},
                {"id": "S2", "node": 2, "start": "0", "end": "1"},
                {"id": "S3", "node": 4, "start": "0", "end": "1"},
            ],
        }
        self.assert_code(payload, "NOT_A_TREE")

    def test_not_a_tree_duplicate_edge(self):
        payload = y_payload()
        payload["edges"][2] = {"u": 3, "v": 2, "length": "4"}  # repeats 2-3
        self.assert_code(payload, "NOT_A_TREE")

    def test_not_a_tree_unknown_node(self):
        payload = y_payload()
        payload["edges"][0]["u"] = 9
        self.assert_code(payload, "NOT_A_TREE")

    def test_nonpositive_length(self):
        payload = y_payload()
        payload["edges"][0]["length"] = "0"
        self.assert_code(payload, "NONPOSITIVE_LENGTH")
        payload["edges"][0]["length"] = "-1.5"
        self.assert_code(payload, "NONPOSITIVE_LENGTH")

    def test_nonpositive_speed(self):
        payload = y_payload()
        payload["speed"] = "0"
        self.assert_code(payload, "NONPOSITIVE_SPEED")

    def test_invalid_number(self):
        payload = y_payload()
        payload["edges"][0]["length"] = "abc"
        self.assert_code(payload, "INVALID_NUMBER")
        payload = y_payload()
        payload["speed"] = "fast"
        self.assert_code(payload, "INVALID_NUMBER")

    def test_sensor_duplicate_node(self):
        payload = y_payload()
        payload["sensors"][2]["node"] = 1
        self.assert_code(payload, "SENSOR_DUPLICATE")

    def test_sensor_duplicate_id(self):
        payload = y_payload()
        payload["sensors"][2]["id"] = "S1"
        self.assert_code(payload, "SENSOR_DUPLICATE")

    def test_sensor_unknown_node(self):
        payload = y_payload()
        payload["sensors"][0]["node"] = 42
        self.assert_code(payload, "SENSOR_NODE_UNKNOWN")

    def test_interval_inverted(self):
        payload = y_payload()
        payload["sensors"][0]["start"], payload["sensors"][0]["end"] = "9", "8"
        self.assert_code(payload, "INTERVAL_INVERTED")

    def test_node_count_bounds(self):
        payload = y_payload()
        payload["nodes"] = [1, 2, 3]
        self.assert_code(payload, "NODE_COUNT")
        payload = y_payload()
        payload["nodes"] = list(range(1, 14))
        self.assert_code(payload, "NODE_COUNT")

    def test_sensor_count_bounds(self):
        payload = y_payload()
        payload["sensors"] = payload["sensors"][:2]
        self.assert_code(payload, "SENSOR_COUNT")
        payload = y_payload()
        payload["sensors"] = payload["sensors"] + [
            {"id": f"X{i}", "node": 1, "start": "0", "end": "1"} for i in range(4)
        ]
        self.assert_code(payload, "SENSOR_COUNT")

    def test_invalid_body(self):
        self.assert_code([1, 2, 3], "INVALID_BODY")


if __name__ == "__main__":
    unittest.main()
