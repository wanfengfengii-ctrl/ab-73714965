"""请求解析与校验：把 JSON 负载精确解析为有理数问题实例。

所有距离与时间一律解析为 fractions.Fraction（经 Decimal 过渡，
拒绝非有限值），校验失败时抛出携带错误码与中文原因的 ApiError。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

from .solver import Edge, Sensor

MIN_NODES, MAX_NODES = 4, 12
MIN_SENSORS, MAX_SENSORS = 3, 6


class ApiError(Exception):
    """可识别的输入错误：code 供程序判断，message 供页面直接展示。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise ApiError(code, message)


@dataclass(frozen=True)
class Problem:
    nodes: list[str]
    edges: list[Edge]
    sensors: list[Sensor]
    speed: Fraction


def parse_number(value: Any, what: str) -> Fraction:
    """把 JSON 数字或十进制字符串精确解析为 Fraction。"""
    if isinstance(value, bool):
        _fail("INVALID_NUMBER", f"{what}必须是十进制数，不能是布尔值。")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            _fail("INVALID_NUMBER", f"{what}无法解析为十进制数：{value!r}。")
    else:
        _fail("INVALID_NUMBER", f"{what}必须是十进制数或十进制字符串。")
    if not d.is_finite():
        _fail("INVALID_NUMBER", f"{what}必须是有限十进制数：{value!r}。")
    return Fraction(d)


def _parse_label(value: Any, what: str) -> str:
    if isinstance(value, bool):
        _fail("INVALID_LABEL", f"{what}必须是字符串标签。")
    if isinstance(value, str):
        label = value.strip()
    elif isinstance(value, (int, Decimal)):
        label = str(value)
    else:
        _fail("INVALID_LABEL", f"{what}必须是字符串标签。")
    if not label:
        _fail("INVALID_LABEL", f"{what}不能为空。")
    return label


def _parse_nodes(payload: dict) -> list[str]:
    raw = payload.get("nodes")
    if not isinstance(raw, list):
        _fail("BAD_REQUEST", "缺少节点列表 nodes（应为数组）。")
    nodes = [_parse_label(x, f"第 {i + 1} 个节点标签") for i, x in enumerate(raw)]
    if not (MIN_NODES <= len(nodes) <= MAX_NODES):
        _fail(
            "NODE_COUNT_OUT_OF_RANGE",
            f"节点数为 {len(nodes)}，应在 {MIN_NODES}~{MAX_NODES} 之间。",
        )
    seen: set[str] = set()
    for n in nodes:
        if n in seen:
            _fail("DUPLICATE_NODE", f"节点标签重复：{n}。")
        seen.add(n)
    return nodes


def _parse_edges(payload: dict, node_set: set[str], n_nodes: int) -> list[Edge]:
    raw = payload.get("edges")
    if not isinstance(raw, list):
        _fail("BAD_REQUEST", "缺少边列表 edges（应为数组）。")
    edges: list[Edge] = []
    seen: set[frozenset[str]] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            _fail("BAD_REQUEST", f"第 {i + 1} 条边应为对象（from/to/length）。")
        frm = item.get("from", item.get("u"))
        to = item.get("to", item.get("v"))
        u = _parse_label(frm, f"第 {i + 1} 条边的起点")
        v = _parse_label(to, f"第 {i + 1} 条边的终点")
        if u not in node_set:
            _fail("UNKNOWN_NODE", f"第 {i + 1} 条边引用了未知节点：{u}。")
        if v not in node_set:
            _fail("UNKNOWN_NODE", f"第 {i + 1} 条边引用了未知节点：{v}。")
        if u == v:
            _fail("SELF_LOOP", f"第 {i + 1} 条边是自环（{u} 到自身），树网不允许。")
        key = frozenset((u, v))
        if key in seen:
            _fail("DUPLICATE_EDGE", f"边 {u}-{v} 重复出现。")
        seen.add(key)
        length = parse_number(item.get("length"), f"边 {u}-{v} 的长度")
        if length <= 0:
            _fail("INVALID_LENGTH", f"边 {u}-{v} 的长度必须为正数，实际为 {item.get('length')!r}。")
        edges.append(Edge(u=u, v=v, length=length))

    expected = n_nodes - 1
    if len(edges) != expected:
        _fail(
            "NOT_A_TREE",
            f"输入不是树：{n_nodes} 个节点的树应恰好有 {expected} 条边，实际为 {len(edges)} 条。",
        )
    _require_connected(node_set, edges)
    return edges


def _require_connected(node_set: set[str], edges: list[Edge]) -> None:
    parent = {n: n for n in node_set}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        ru, rv = find(e.u), find(e.v)
        if ru != rv:
            parent[ru] = rv
    roots = {find(n) for n in node_set}
    if len(roots) != 1:
        _fail(
            "NOT_A_TREE",
            f"输入不是树：网络不连通（存在 {len(roots)} 个互不相连的部分）。",
        )


def _parse_speed(payload: dict) -> Fraction:
    if "speed" not in payload:
        _fail("BAD_REQUEST", "缺少传播速度 speed。")
    speed = parse_number(payload.get("speed"), "传播速度")
    if speed <= 0:
        _fail("INVALID_SPEED", f"传播速度必须为正数，实际为 {payload.get('speed')!r}。")
    return speed


def _parse_interval(value: Any, sid: str) -> tuple[Fraction, Fraction]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo_raw, hi_raw = value[0], value[1]
    elif isinstance(value, dict):
        lo_raw = value.get("lo", value.get("min"))
        hi_raw = value.get("hi", value.get("max"))
    else:
        _fail("BAD_REQUEST", f"传感器 {sid} 的到时区间应为 [下限, 上限]。")
    lo = parse_number(lo_raw, f"传感器 {sid} 的到时下限")
    hi = parse_number(hi_raw, f"传感器 {sid} 的到时上限")
    if lo > hi:
        _fail(
            "INVALID_INTERVAL",
            f"传感器 {sid} 的到时区间倒置：下限 {lo_raw!r} 大于上限 {hi_raw!r}。",
        )
    return lo, hi


def _parse_sensors(payload: dict, node_set: set[str]) -> list[Sensor]:
    raw = payload.get("sensors")
    if not isinstance(raw, list):
        _fail("BAD_REQUEST", "缺少传感器列表 sensors（应为数组）。")
    if not (MIN_SENSORS <= len(raw) <= MAX_SENSORS):
        _fail(
            "SENSOR_COUNT_OUT_OF_RANGE",
            f"传感器数量为 {len(raw)}，应在 {MIN_SENSORS}~{MAX_SENSORS} 之间。",
        )
    sensors: list[Sensor] = []
    used_ids: set[str] = set()
    used_nodes: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            _fail("BAD_REQUEST", f"第 {i + 1} 条传感器记录应为对象（id/node/arrival）。")
        sid = _parse_label(item.get("id"), f"第 {i + 1} 条传感器记录的编号")
        if sid in used_ids:
            _fail("DUPLICATE_SENSOR", f"传感器编号重复：{sid}。")
        used_ids.add(sid)
        node = _parse_label(item.get("node"), f"传感器 {sid} 的挂载节点")
        if node not in node_set:
            _fail("UNKNOWN_NODE", f"传感器 {sid} 挂载在未知节点 {node} 上。")
        if node in used_nodes:
            _fail("DUPLICATE_SENSOR", f"传感器重复：节点 {node} 上已挂有传感器。")
        used_nodes.add(node)
        lo, hi = _parse_interval(item.get("arrival"), sid)
        sensors.append(Sensor(sid=sid, node=node, lo=lo, hi=hi))
    return sensors


def parse_request(payload: Any) -> Problem:
    """把 JSON 负载解析为 Problem；任何不合法输入都抛出 ApiError。"""
    if not isinstance(payload, dict):
        _fail("BAD_REQUEST", "请求体应为 JSON 对象。")
    nodes = _parse_nodes(payload)
    node_set = set(nodes)
    edges = _parse_edges(payload, node_set, len(nodes))
    speed = _parse_speed(payload)
    sensors = _parse_sensors(payload, node_set)
    return Problem(nodes=nodes, edges=edges, sensors=sensors, speed=speed)
