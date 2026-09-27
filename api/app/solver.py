"""Exact continuous solver for cable-fault localization on a tree network.

Model
-----
The cable network is a tree: nodes joined by edges with positive lengths.
A fault happens at one unknown point ``x`` (anywhere along an edge, not
only at nodes) at one unknown occurrence time ``t``.  Sensor ``i``, fixed
at node ``s_i``, records an arrival-time window ``[a_i, b_i]``; the record
is explained iff

    a_i <= t + dist(x, s_i) / speed <= b_i .

For a fixed edge ``(u, v)`` of length ``L`` write the unknown point as
``p`` in ``[0, L]`` (distance from ``u``).  On a tree the path from ``x``
to ``s_i`` is unique, so ``dist(x, s_i) = c_i + sign_i * p`` with
``sign_i`` in ``{+1, -1}``: the distance is a single affine function of
``p``, never piecewise.  Multiplying the record inequality by the speed
gives, with the scaled occurrence time ``tau = speed * t``,

    A_i <= tau + sign_i * p <= B_i,
    A_i = speed * a_i - c_i,  B_i = speed * b_i - c_i .

Each record is therefore a strip between two parallel lines (slope +-1)
in the ``(p, tau)`` plane; the feasible set per edge is a convex polygon
clipped to ``0 <= p <= L``, so its projection on the position axis is a
single closed interval.  That interval is computed exactly with
:class:`fractions.Fraction` arithmetic by scanning the candidate boundary
points (edge ends and pairwise A-line/B-line intersections), and the
attainable ``tau`` range follows from the lower/upper envelopes.  There
is no discrete sampling and no node-only enumeration anywhere.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

from .rational import RationalParseError, parse_rational

MIN_NODES, MAX_NODES = 4, 12
MIN_SENSORS, MAX_SENSORS = 3, 6


class LocateError(Exception):
    """Domain error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorSpec:
    sid: str
    node: int
    start: Fraction
    end: Fraction


@dataclass(frozen=True)
class EdgeSpec:
    u: int
    v: int
    length: Fraction


@dataclass(frozen=True)
class ProblemSpec:
    nodes: Tuple[int, ...]
    edges: Tuple[EdgeSpec, ...]
    speed: Fraction
    sensors: Tuple[SensorSpec, ...]


def validate_payload(payload) -> ProblemSpec:
    """Validate the request body and return a normalized problem spec.

    Every rejection raises :class:`LocateError` with a stable code and an
    identifiable reason, in a deterministic check order.
    """
    if not isinstance(payload, dict):
        raise LocateError("INVALID_BODY", "请求体必须是 JSON 对象")

    # ---- nodes -------------------------------------------------------
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise LocateError("INVALID_NODES", "nodes 必须是节点编号数组")
    nodes: List[int] = []
    seen_nodes = set()
    for item in raw_nodes:
        if isinstance(item, bool) or not isinstance(item, int):
            raise LocateError("INVALID_NODES", f"节点编号必须是整数: {item!r}")
        if item in seen_nodes:
            raise LocateError("INVALID_NODES", f"节点编号重复: {item}")
        seen_nodes.add(item)
        nodes.append(item)
    if not MIN_NODES <= len(nodes) <= MAX_NODES:
        raise LocateError(
            "NODE_COUNT",
            f"节点数必须在 {MIN_NODES}~{MAX_NODES} 之间，当前 {len(nodes)} 个",
        )

    # ---- edges (tree check via union-find) ---------------------------
    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        raise LocateError("NOT_A_TREE", "edges 必须是边数组")
    if len(raw_edges) != len(nodes) - 1:
        raise LocateError(
            "NOT_A_TREE",
            f"树网应恰好有 节点数-1={len(nodes) - 1} 条边，当前 {len(raw_edges)} 条",
        )
    parent = {n: n for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges: List[EdgeSpec] = []
    seen_pairs = set()
    for idx, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            raise LocateError("NOT_A_TREE", f"第 {idx + 1} 条边必须是对象 {{u, v, length}}")
        u, v = item.get("u"), item.get("v")
        if u not in seen_nodes or v not in seen_nodes:
            raise LocateError(
                "NOT_A_TREE",
                f"第 {idx + 1} 条边引用了未声明的节点: u={u!r}, v={v!r}",
            )
        if u == v:
            raise LocateError("NOT_A_TREE", f"第 {idx + 1} 条边是自环: {u}-{v}")
        pair = (min(u, v), max(u, v))
        if pair in seen_pairs:
            raise LocateError(
                "NOT_A_TREE", f"节点 {pair[0]} 与 {pair[1]} 之间存在重复边"
            )
        seen_pairs.add(pair)
        try:
            length = parse_rational(item.get("length"), f"第 {idx + 1} 条边 ({u}-{v}) 长度")
        except RationalParseError as exc:
            raise LocateError("INVALID_NUMBER", str(exc)) from exc
        if length <= 0:
            raise LocateError(
                "NONPOSITIVE_LENGTH",
                f"第 {idx + 1} 条边 ({u}-{v}) 长度必须为正，当前 {length}",
            )
        ru, rv = find(u), find(v)
        if ru == rv:
            raise LocateError("NOT_A_TREE", f"边 ({u}-{v}) 使网络成环，输入不是树")
        parent[ru] = rv
        edges.append(EdgeSpec(u, v, length))
    if len({find(n) for n in nodes}) != 1:
        raise LocateError("NOT_A_TREE", "网络不连通，输入不是树")

    # ---- speed -------------------------------------------------------
    try:
        speed = parse_rational(payload.get("speed"), "传播速度 speed")
    except RationalParseError as exc:
        raise LocateError("INVALID_NUMBER", str(exc)) from exc
    if speed <= 0:
        raise LocateError("NONPOSITIVE_SPEED", f"传播速度必须为正，当前 {speed}")

    # ---- sensors -----------------------------------------------------
    raw_sensors = payload.get("sensors")
    if not isinstance(raw_sensors, list):
        raise LocateError("INVALID_SENSORS", "sensors 必须是传感器数组")
    if not MIN_SENSORS <= len(raw_sensors) <= MAX_SENSORS:
        raise LocateError(
            "SENSOR_COUNT",
            f"传感器数量必须在 {MIN_SENSORS}~{MAX_SENSORS} 之间，当前 {len(raw_sensors)} 台",
        )
    sensors: List[SensorSpec] = []
    used_ids, used_nodes = set(), set()
    for idx, item in enumerate(raw_sensors):
        if not isinstance(item, dict):
            raise LocateError("INVALID_SENSORS", f"第 {idx + 1} 台传感器必须是对象")
        sid = item.get("id")
        if sid is None:
            sid = f"S{idx + 1}"
        if not isinstance(sid, str) or not sid.strip():
            raise LocateError("INVALID_SENSORS", f"第 {idx + 1} 台传感器 id 必须是非空字符串")
        sid = sid.strip()
        if sid in used_ids:
            raise LocateError("SENSOR_DUPLICATE", f"传感器 id 重复: {sid}")
        used_ids.add(sid)
        node = item.get("node")
        if node not in seen_nodes:
            raise LocateError(
                "SENSOR_NODE_UNKNOWN", f"传感器 {sid} 挂在未声明的节点上: {node!r}"
            )
        if node in used_nodes:
            raise LocateError(
                "SENSOR_DUPLICATE", f"节点 {node} 上重复挂载传感器（{sid}）"
            )
        used_nodes.add(node)
        try:
            start = parse_rational(item.get("start"), f"传感器 {sid} 到时起点")
            end = parse_rational(item.get("end"), f"传感器 {sid} 到时终点")
        except RationalParseError as exc:
            raise LocateError("INVALID_NUMBER", str(exc)) from exc
        if start > end:
            raise LocateError(
                "INTERVAL_INVERTED",
                f"传感器 {sid} 的到时区间倒置: [{start}, {end}]",
            )
        sensors.append(SensorSpec(sid, node, start, end))

    return ProblemSpec(tuple(nodes), tuple(edges), speed, tuple(sensors))


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """One closed feasible interval on one edge (exact rationals)."""

    edge_index: int
    u: int
    v: int
    length: Fraction
    p_lo: Fraction  # position range, distance from u
    p_hi: Fraction
    mileage_lo: Fraction  # chainage range measured from the first node
    mileage_hi: Fraction
    t_lo: Fraction  # occurrence-time range consistent with this segment
    t_hi: Fraction


@dataclass(frozen=True)
class SolveResult:
    speed: Fraction
    segments: Tuple[Segment, ...]
    t_lo: Fraction  # overall occurrence-time range
    t_hi: Fraction


@dataclass(frozen=True)
class _EdgeGeometry:
    """Per-edge view of the records: A_i <= tau + sign_i * p <= B_i."""

    index: int
    u: int
    v: int
    length: Fraction
    signs: Tuple[int, ...]
    lows: Tuple[Fraction, ...]  # A_i
    highs: Tuple[Fraction, ...]  # B_i


def _bfs_distances(adjacency: Dict[int, List[Tuple[int, Fraction, int]]], source: int):
    dist = {source: Fraction(0)}
    queue = deque([source])
    while queue:
        x = queue.popleft()
        for y, w, _idx in adjacency[x]:
            if y not in dist:
                dist[y] = dist[x] + w
                queue.append(y)
    return dist


def _edge_geometry(
    spec: ProblemSpec,
    edge: EdgeSpec,
    index: int,
    sensor_dists: Sequence[Dict[int, Fraction]],
) -> _EdgeGeometry:
    signs, lows, highs = [], [], []
    length = edge.length
    for si, sensor in enumerate(spec.sensors):
        du = sensor_dists[si][edge.u]
        dv = sensor_dists[si][edge.v]
        if du + length == dv:  # sensor lies on u's side of the cut
            signs.append(1)
            c = du
        elif dv + length == du:  # sensor lies on v's side
            signs.append(-1)
            c = length + dv
        else:  # unreachable on a validated tree
            raise LocateError("NOT_A_TREE", "网络结构异常：边两侧距离不一致")
        lows.append(spec.speed * sensor.start - c)
        highs.append(spec.speed * sensor.end - c)
    return _EdgeGeometry(index, edge.u, edge.v, length, tuple(signs), tuple(lows), tuple(highs))


def _feasible_interval_on_edge(geom: _EdgeGeometry):
    """Return ``(p_lo, p_hi, tau_lo, tau_hi)`` for one edge, or ``None``.

    ``p`` range is the projection of the feasible convex polygon on the
    position axis (a single closed interval); ``tau`` range is the set of
    scaled occurrence times attainable over that interval.
    """
    m = len(geom.signs)
    length = geom.length
    signs, low, high = geom.signs, geom.lows, geom.highs

    def lower(p: Fraction) -> Fraction:
        return max(low[i] - signs[i] * p for i in range(m))

    def upper(p: Fraction) -> Fraction:
        return min(high[i] - signs[i] * p for i in range(m))

    def feasible(p: Fraction) -> bool:
        return lower(p) <= upper(p)

    # Candidate boundary points of the feasible projection: the edge ends
    # and every intersection of a lower-envelope line (A_i - s_i p) with
    # an upper-envelope line (B_j - s_j p).  Boundary points where the
    # active lines are parallel coincide with such an intersection of the
    # taking-over line, so this set is complete.
    candidates = {Fraction(0), length}
    for i in range(m):
        for j in range(m):
            if signs[i] != signs[j]:
                p = (low[i] - high[j]) / (signs[i] - signs[j])
                if 0 <= p <= length:
                    candidates.add(p)
    ordered = sorted(candidates)

    # Feasible atomic pieces: candidate points themselves, plus whole
    # closed gaps whose midpoint is feasible (no boundary can hide inside
    # a gap, so the midpoint decides).
    pieces: List[Tuple[Fraction, Fraction]] = []
    for p in ordered:
        if feasible(p):
            pieces.append((p, p))
    for left, right in zip(ordered, ordered[1:]):
        if left < right and feasible((left + right) / 2):
            pieces.append((left, right))
    if not pieces:
        return None

    # Merge adjoining pieces on this edge: closed intervals that touch
    # (start <= previous end) belong to the same reported segment.
    pieces.sort()
    merged_lo, merged_hi = pieces[0]
    for start, end in pieces[1:]:
        if start <= merged_hi:
            merged_hi = max(merged_hi, end)
        else:  # cannot happen: the projection of a convex set is one interval
            raise LocateError("INTERNAL", "同一边上出现互不相接的可行区间")
    p_lo, p_hi = merged_lo, merged_hi

    # tau range over [p_lo, p_hi]: lower() is convex piecewise linear with
    # breakpoints where two A-lines cross, upper() is concave with
    # breakpoints where two B-lines cross; extrema sit at ends or there.
    probe = {p_lo, p_hi}
    for i in range(m):
        for j in range(i + 1, m):
            if signs[i] != signs[j]:
                pa = (low[i] - low[j]) / (signs[i] - signs[j])
                if p_lo <= pa <= p_hi:
                    probe.add(pa)
    tau_lo = min(lower(p) for p in probe)
    probe_hi = {p_lo, p_hi}
    for i in range(m):
        for j in range(i + 1, m):
            if signs[i] != signs[j]:
                pb = (high[i] - high[j]) / (signs[i] - signs[j])
                if p_lo <= pb <= p_hi:
                    probe_hi.add(pb)
    tau_hi = max(upper(p) for p in probe_hi)
    return p_lo, p_hi, tau_lo, tau_hi


def _solve_segments(spec: ProblemSpec, adjacency, sensor_dists) -> List[Segment]:
    segments: List[Segment] = []
    root = spec.nodes[0]
    root_dist = _bfs_distances(adjacency, root)
    for index, edge in enumerate(spec.edges):
        geom = _edge_geometry(spec, edge, index, sensor_dists)
        found = _feasible_interval_on_edge(geom)
        if found is None:
            continue
        p_lo, p_hi, tau_lo, tau_hi = found
        # Chainage: distance from the first node along the unique path.
        if root_dist[edge.u] + edge.length == root_dist[edge.v]:
            mileage_lo = root_dist[edge.u] + p_lo
            mileage_hi = root_dist[edge.u] + p_hi
        else:
            mileage_lo = root_dist[edge.v] + (edge.length - p_hi)
            mileage_hi = root_dist[edge.v] + (edge.length - p_lo)
        segments.append(
            Segment(
                edge_index=index,
                u=edge.u,
                v=edge.v,
                length=edge.length,
                p_lo=p_lo,
                p_hi=p_hi,
                mileage_lo=mileage_lo,
                mileage_hi=mileage_hi,
                t_lo=tau_lo / spec.speed,
                t_hi=tau_hi / spec.speed,
            )
        )
    return segments


def _first_empty_sensor(spec: ProblemSpec, adjacency, sensor_dists) -> SensorSpec:
    """Earliest sensor (input order) whose window empties the joint set."""
    for k in range(2, len(spec.sensors) + 1):
        sub = ProblemSpec(spec.nodes, spec.edges, spec.speed, spec.sensors[:k])
        if not _solve_segments(sub, adjacency, sensor_dists):
            return spec.sensors[k - 1]
    return spec.sensors[-1]  # unreachable: the full set is infeasible


def solve(payload) -> SolveResult:
    """Validate, then return every feasible closed segment exactly."""
    spec = validate_payload(payload)
    adjacency: Dict[int, List[Tuple[int, Fraction, int]]] = {n: [] for n in spec.nodes}
    for idx, edge in enumerate(spec.edges):
        adjacency[edge.u].append((edge.v, edge.length, idx))
        adjacency[edge.v].append((edge.u, edge.length, idx))
    sensor_dists = [_bfs_distances(adjacency, s.node) for s in spec.sensors]

    segments = _solve_segments(spec, adjacency, sensor_dists)
    if not segments:
        bad = _first_empty_sensor(spec, adjacency, sensor_dists)
        k = spec.sensors.index(bad) + 1
        raise LocateError(
            "NO_FEASIBLE_POSITION",
            f"没有任何管段位置能同时解释全部到时记录；按录入顺序，加入第 {k} 台传感器 "
            f"{bad.sid}（节点 {bad.node}，到时窗口 [{bad.start}, {bad.end}]）后交集首次为空",
            first_empty_sensor=bad.sid,
            sensor_index=k,
            considered_sensors=[s.sid for s in spec.sensors[:k]],
        )

    return SolveResult(
        speed=spec.speed,
        segments=tuple(segments),
        t_lo=min(s.t_lo for s in segments),
        t_hi=max(s.t_hi for s in segments),
    )
