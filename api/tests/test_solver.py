"""求解器单元测试：连续区间、精确有理数、合并与首条空交集记录。"""

from fractions import Fraction

from app.solver import (
    Edge,
    Segment,
    Sensor,
    Tree,
    first_infeasible_prefix,
    locate,
    merge_segments,
    solve_edge,
)

F = Fraction


def branch_problem():
    """分叉树：故障在 N2-N3 上距 N2 600m 处，t0=10s，v=1500m/s。"""
    nodes = ["N1", "N2", "N3", "N4", "N5", "N6"]
    edges = [
        Edge("N1", "N2", F(1500)),
        Edge("N2", "N3", F(1200)),
        Edge("N2", "N4", F(900)),
        Edge("N3", "N5", F(600)),
        Edge("N4", "N6", F(600)),
    ]
    sensors = [
        Sensor("S1", "N1", F("11.3"), F("11.5")),
        Sensor("S2", "N5", F("10.7"), F("10.9")),
        Sensor("S3", "N6", F("11.3"), F("11.5")),
    ]
    return Tree(nodes, edges), sensors, F(1500)


def test_branch_single_segment_exact():
    tree, sensors, speed = branch_problem()
    segments = locate(tree, sensors, speed)
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.u, seg.v) == ("N2", "N3")
    # 里程闭区间精确为 [450, 750]，包含真实故障点 600
    assert seg.s_lo == F(450)
    assert seg.s_hi == F(750)
    # 发生时刻范围精确为 [9.9, 10.1]，包含真实时刻 10
    assert seg.t_lo == F(99, 10)
    assert seg.t_hi == F(101, 10)


def test_star_multiple_segments_all_listed():
    """星形网：记录共同指向 5 段海缆，必须全部列出而非单点。"""
    nodes = ["N0", "N1", "N2", "N3", "N4", "N5"]
    edges = [Edge("N0", f"N{i}", F(1000)) for i in range(1, 6)]
    sensors = [
        Sensor("SA", "N1", F("11.3"), F("11.5")),
        Sensor("SB", "N2", F("11.3"), F("11.5")),
        Sensor("SC", "N3", F("11.3"), F("11.5")),
    ]
    tree = Tree(nodes, edges)
    segments = locate(tree, sensors, F(1000))
    assert len(segments) == 5
    by_edge = {(s.u, s.v): s for s in segments}
    # 挂了传感器的三条臂：仅靠近中心节点的 [0, 100] 米可行
    for i in (1, 2, 3):
        seg = by_edge[("N0", f"N{i}")]
        assert (seg.s_lo, seg.s_hi) == (F(0), F(100))
        assert (seg.t_lo, seg.t_hi) == (F(103, 10), F(105, 10))
    # 未挂传感器的两条臂：整条臂都无法排除（单侧约束，时刻范围有界）
    for i in (4, 5):
        seg = by_edge[("N0", f"N{i}")]
        assert (seg.s_lo, seg.s_hi) == (F(0), F(1000))
        assert (seg.t_lo, seg.t_hi) == (F(93, 10), F(105, 10))


def test_exact_point_with_decimal_lengths():
    """零宽到时区间 + 小数边长：精确锁定点位置，验证有理数运算无浮点误差。"""
    nodes = ["A", "B", "C", "D"]
    edges = [
        Edge("A", "B", F("0.3")),
        Edge("B", "C", F("0.3")),
        Edge("C", "D", F("0.3")),
    ]
    # 真实故障：B-C 上距 B 0.15，t0 = 0
    sensors = [
        Sensor("SA", "A", F("0.45"), F("0.45")),
        Sensor("SB", "D", F("0.45"), F("0.45")),
        Sensor("SC", "B", F("0.15"), F("0.15")),
    ]
    tree = Tree(nodes, edges)
    segments = locate(tree, sensors, F(1))
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.u, seg.v) == ("B", "C")
    assert seg.s_lo == seg.s_hi == F(3, 20)  # 0.15 的精确值
    assert seg.t_lo == seg.t_hi == F(0)


def test_minus_side_only_edge():
    """全部传感器位于边的同一侧（负侧）：时刻范围仍有界。"""
    nodes = ["A", "B", "C", "D"]
    edges = [Edge("A", "B", F(1000)), Edge("B", "C", F(1000)), Edge("C", "D", F(1000))]
    sensors = [
        Sensor("SB", "B", F("1.7"), F("1.9")),
        Sensor("SC", "C", F("2.7"), F("2.9")),
        Sensor("SD", "D", F("3.7"), F("3.9")),
    ]
    tree = Tree(nodes, edges)
    segments = locate(tree, sensors, F(1000))
    by_edge = {(s.u, s.v): s for s in segments}
    assert set(by_edge) == {("A", "B"), ("B", "C")}
    ab = by_edge[("A", "B")]
    assert (ab.s_lo, ab.s_hi) == (F(0), F(1000))
    assert (ab.t_lo, ab.t_hi) == (F(7, 10), F(19, 10))
    bc = by_edge[("B", "C")]
    assert (bc.s_lo, bc.s_hi) == (F(0), F(100))


def test_first_infeasible_prefix_is_stable():
    """逐条加入记录，首条使交集为空的记录应被稳定指出。"""
    nodes = ["N1", "N2", "N3", "N4"]
    edges = [Edge("N1", "N2", F(1000)), Edge("N2", "N3", F(1000)), Edge("N3", "N4", F(1000))]
    sensors = [
        Sensor("SA", "N1", F(0), F(1)),
        Sensor("SB", "N4", F(0), F(1)),
        Sensor("SC", "N2", F(100), F(101)),
    ]
    tree = Tree(nodes, edges)
    assert locate(tree, sensors, F(1000)) == []
    # 前两条可共同成立，加入第三条（下标 2）后交集为空
    assert first_infeasible_prefix(tree, sensors, F(1000)) == 2
    # 重复调用结果一致（稳定性）
    assert first_infeasible_prefix(tree, sensors, F(1000)) == 2


def test_merge_segments_joins_touching_pieces_on_same_edge():
    pieces = [
        Segment(0, "A", "B", F(100), F(0), F(40), F(1), F(2)),
        Segment(0, "A", "B", F(100), F(40), F(70), F(0), F(3)),  # 端点相触
        Segment(0, "A", "B", F(100), F(80), F(100), F(5), F(6)),  # 与前者不相接
        Segment(1, "B", "C", F(50), F(0), F(10), F(0), F(1)),  # 另一条边
    ]
    merged = merge_segments(pieces)
    assert len(merged) == 3
    first = merged[0]
    assert (first.s_lo, first.s_hi) == (F(0), F(70))
    assert (first.t_lo, first.t_hi) == (F(0), F(3))
    assert merged[1].s_lo == F(80)
    assert merged[2].edge_index == 1


def test_solve_edge_returns_none_when_same_side_conflicts():
    nodes = ["A", "B", "C", "D"]
    edges = [Edge("A", "B", F(100)), Edge("B", "C", F(100)), Edge("C", "D", F(100))]
    # 两台传感器都在边的同侧，但到时窗口互不重叠
    sensors = [
        Sensor("S1", "C", F(0), F(1)),
        Sensor("S2", "D", F(10), F(11)),
        Sensor("S3", "A", F(0), F(1)),
    ]
    tree = Tree(nodes, edges)
    assert solve_edge(tree, 0, sensors, F(1)) is None
