"""海缆故障定位核心求解器。

在树状海缆网络上，根据多台水听器的到时闭区间，把每条边上的
连续故障位置 s 与未知的故障发生时刻 t0 联合起来精确求解。

数学模型
--------
设传播速度为 v（米/秒）。故障发生在某条边 (u, w) 上、距 u 端 s 米处
（0 <= s <= L，L 为边长），发生时刻为 t0。树中路径唯一，因此对挂在
节点 n_i 的传感器 i：

    到时 t_i = t0 + d(x, n_i) / v

其中 d(x, n_i) = c_i + e_i * s，e_i ∈ {+1, -1}：
  - 若 n_i 在边的 u 侧，则 d = dist(n_i, u) + s        （e_i = +1）
  - 若 n_i 在边的 w 侧，则 d = dist(n_i, w) + (L - s)  （e_i = -1）

令 tau = v * t0（距离量纲），每条到时记录 [a_i, b_i] 化为线性约束：

    v*a_i - c_i <= tau + e_i * s <= v*b_i - c_i

对每条边，(s, tau) 的可行域是若干半平面与条带 [0, L] x R 的交
（凸集），其在 s 轴与 t0 轴上的投影各为一个闭区间，可解析求得。
全部运算使用 fractions.Fraction 做精确有理数计算：
不离散采样，也不只枚举节点。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional


@dataclass(frozen=True)
class Edge:
    """一条海缆管段（无向边）。length 为长度（米），必须为正。"""

    u: str
    v: str
    length: Fraction


@dataclass(frozen=True)
class Sensor:
    """挂在节点上的水听器，到时为闭区间 [lo, hi]（秒）。"""

    sid: str
    node: str
    lo: Fraction
    hi: Fraction


@dataclass(frozen=True)
class Segment:
    """某条边上可共同成立的故障区域（均为闭区间）。

    s_lo/s_hi：故障点距 u 端的里程范围（米）；
    t_lo/t_hi：可共同成立的故障发生时刻范围（秒）。
    """

    edge_index: int
    u: str
    v: str
    length: Fraction
    s_lo: Fraction
    s_hi: Fraction
    t_lo: Fraction
    t_hi: Fraction


class Tree:
    """节点数很小的树网（4~12 个节点），预计算节点两两距离。"""

    def __init__(self, nodes: list[str], edges: list[Edge]):
        self.nodes = list(nodes)
        self.edges = list(edges)
        self.adj: dict[str, list[tuple[str, int]]] = {n: [] for n in self.nodes}
        for i, e in enumerate(self.edges):
            self.adj[e.u].append((e.v, i))
            self.adj[e.v].append((e.u, i))
        self.dist: dict[str, dict[str, Fraction]] = {
            n: self._distances_from(n) for n in self.nodes
        }

    def _distances_from(self, src: str) -> dict[str, Fraction]:
        d = {src: Fraction(0)}
        stack = [src]
        while stack:
            a = stack.pop()
            for b, ei in self.adj[a]:
                if b not in d:
                    d[b] = d[a] + self.edges[ei].length
                    stack.append(b)
        return d


def solve_edge(
    tree: Tree, edge_index: int, sensors: list[Sensor], speed: Fraction
) -> Optional[Segment]:
    """精确求解一条边上的可行故障区域；不可行时返回 None。

    对每条到时记录 [a_i, b_i] 有  lo_i <= tau + e_i*s <= hi_i，
    其中 lo_i = v*a_i - c_i，hi_i = v*b_i - c_i。按 e_i 分两侧：
      + 侧：A = max lo_i，C = min hi_i；  - 侧：B = max lo_i，D = min hi_i。
    存在 s 使 max(A-s, B+s) <= min(C-s, D+s) 当且仅当：
      A <= C，B <= D（同侧记录自洽），且
      (A - D)/2 <= s <= (C - B)/2（异侧记录夹出的里程范围）。
    """
    e = tree.edges[edge_index]
    L = e.length

    plus_lo: list[Fraction] = []
    plus_hi: list[Fraction] = []
    minus_lo: list[Fraction] = []
    minus_hi: list[Fraction] = []

    for s in sensors:
        du = tree.dist[s.node][e.u]
        dv = tree.dist[s.node][e.v]
        if du < dv:  # 传感器在 u 侧：d = du + s
            c, plus = du, True
        else:  # 传感器在 v 侧：d = (dv + L) - s
            c, plus = dv + L, False
        lo = speed * s.lo - c
        hi = speed * s.hi - c
        if plus:
            plus_lo.append(lo)
            plus_hi.append(hi)
        else:
            minus_lo.append(lo)
            minus_hi.append(hi)

    s_lo = Fraction(0)
    s_hi = L

    if plus_lo:
        A = max(plus_lo)
        C = min(plus_hi)
        if A > C:  # 同侧记录互相矛盾
            return None
    if minus_lo:
        B = max(minus_lo)
        D = min(minus_hi)
        if B > D:
            return None
    if plus_lo and minus_lo:
        # 异侧记录共同夹出里程闭区间
        s_lo = max(s_lo, (max(plus_lo) - min(minus_hi)) / 2)
        s_hi = min(s_hi, (min(plus_hi) - max(minus_lo)) / 2)

    if s_lo > s_hi:
        return None

    # tau 的取值范围：对 s ∈ [s_lo, s_hi]，
    #   tau >= LB(s) = max(A - s, B + s)（凸，极小在两侧交点 (A-B)/2 处）
    #   tau <= UB(s) = min(C - s, D + s)（凹，极大在两侧交点 (C-D)/2 处）
    if plus_lo and minus_lo:
        A, C = max(plus_lo), min(plus_hi)
        B, D = max(minus_lo), min(minus_hi)
        s1 = min(max((A - B) / 2, s_lo), s_hi)
        tau_lo = max(A - s1, B + s1)
        s2 = min(max((C - D) / 2, s_lo), s_hi)
        tau_hi = min(C - s2, D + s2)
    elif plus_lo:
        A, C = max(plus_lo), min(plus_hi)
        tau_lo = A - s_hi  # LB = A - s 递减
        tau_hi = C - s_lo  # UB = C - s 递减
    else:
        B, D = max(minus_lo), min(minus_hi)
        tau_lo = B + s_lo  # LB = B + s 递增
        tau_hi = D + s_hi  # UB = D + s 递增

    return Segment(
        edge_index=edge_index,
        u=e.u,
        v=e.v,
        length=L,
        s_lo=s_lo,
        s_hi=s_hi,
        t_lo=tau_lo / speed,
        t_hi=tau_hi / speed,
    )


def merge_segments(segments: list[Segment]) -> list[Segment]:
    """合并同一条边上相接（闭区间重叠或端点相触）的结果。

    连续求解在每条边上本就直接给出一个凸（即单一）闭区间，
    这里再做一次归并作为保险，保证同一边上不会出现相邻碎片。
    """
    by_edge: dict[int, list[Segment]] = {}
    order: list[int] = []
    for seg in segments:
        if seg.edge_index not in by_edge:
            by_edge[seg.edge_index] = []
            order.append(seg.edge_index)
        by_edge[seg.edge_index].append(seg)

    merged: list[Segment] = []
    for ei in order:
        pieces = sorted(by_edge[ei], key=lambda s: (s.s_lo, s.s_hi))
        cur = pieces[0]
        for nxt in pieces[1:]:
            if nxt.s_lo <= cur.s_hi:  # 重叠或端点相触
                cur = Segment(
                    edge_index=cur.edge_index,
                    u=cur.u,
                    v=cur.v,
                    length=cur.length,
                    s_lo=cur.s_lo,
                    s_hi=max(cur.s_hi, nxt.s_hi),
                    t_lo=min(cur.t_lo, nxt.t_lo),
                    t_hi=max(cur.t_hi, nxt.t_hi),
                )
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
    return merged


def locate(
    tree: Tree, sensors: list[Sensor], speed: Fraction
) -> list[Segment]:
    """对全网逐边精确求解，返回所有可共同成立的管段闭区间。"""
    found: list[Segment] = []
    for ei in range(len(tree.edges)):
        seg = solve_edge(tree, ei, sensors, speed)
        if seg is not None:
            found.append(seg)
    return merge_segments(found)


def first_infeasible_prefix(
    tree: Tree, sensors: list[Sensor], speed: Fraction
) -> Optional[int]:
    """按录入顺序逐条加入传感器记录，返回首个使交集为空的记录下标。

    返回 0 基下标；若全部记录联合可行则返回 None。
    结果只与输入顺序有关，因此对同一输入是稳定（确定）的。
    """
    for k in range(1, len(sensors) + 1):
        prefix = sensors[:k]
        if not any(
            solve_edge(tree, ei, prefix, speed) is not None
            for ei in range(len(tree.edges))
        ):
            return k - 1
    return None
