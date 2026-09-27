# 海缆故障定位系统（水听器到时联合解算）

海上风电场检修后，工程师用多处水听器的到时记录定位海缆故障。系统在**带长度的树网**上，
把每条边上的**连续位置**与**未知发生时刻**联合求解，全程使用**有理数精确运算**，
输出所有可能的管段、各段里程范围和可共同成立的故障发生时刻范围——
当记录共同指向多段海缆时列出**全部待检区段**，而不是给出某个"最近传感器旁"的单一断点。

## 模型与算法

- 故障发生在某条边上距起点 `p ∈ [0, L]` 处，发生时刻 `t` 未知；
- 传感器 `i`（挂在节点上）记录到时闭区间 `[a_i, b_i]`，记录可解释当且仅当
  `a_i ≤ t + dist(x, s_i) / v ≤ b_i`；
- 树上路径唯一，故在固定边上 `dist(x, s_i) = c_i ± p`（仿射、非分段）。
  令 `τ = v·t`，每条记录化为 `A_i ≤ τ ± p ≤ B_i`——`(p, τ)` 平面上的斜条带；
- 每条边的可行域是凸多边形与 `[0, L]` 的交，其在位置轴上的投影是**单个闭区间**。
  求解器用 `Fraction` 精确扫描候选边界点（边端点与 A/B 线交点）得到该区间，
  相接的可行片段在同一边上被合并，再由上下包络的断点求出 `τ`（即发生时刻）范围；
- **不离散采样、不只枚举节点**；里程自首个节点沿唯一路径累计；
- 无可行位置时，按录入顺序找出**首条使交集为空的传感器记录**并稳定报告。

## 目录结构

```
api/            定位 API（Python 标准库实现，无第三方依赖）
  app/solver.py   精确求解器与输入校验
  app/server.py   HTTP 服务（GET /health, POST /api/locate）
  Dockerfile
web/            前端静态页面 + 构建脚本 + nginx 配置
  src/            index.html / app.js / styles.css
  build.py        前端构建（校验并产出 dist/，无需 npm）
  Dockerfile      多阶段：python 构建 -> nginx 伺服
tests/          单元与 API 测试（unittest）
verify/         一次性验证服务（代码测试 + 前端构建 + 定位 API 冒烟）
docker-compose.yml
```

## 快速开始（Docker）

```bash
docker compose up --build web api     # 启动 Web 与 API
# 打开 http://localhost:8080
```

宿主机端口可配置（默认 Web 8080、API 8000）：

```bash
cp .env.example .env      # 修改 WEB_HOST_PORT / API_HOST_PORT
# 或： WEB_HOST_PORT=9000 API_HOST_PORT=9001 docker compose up --build
```

Web 与 API 均带健康检查（`GET /health`），Compose 的就绪依赖基于健康状态。

## 一次性验证（verify）

```bash
docker compose up --build --exit-code-from verify
echo $?        # 0 = 全部通过；非 0 = 失败
```

`verify` 在 `api`、`web` 健康后依次执行：**代码测试 → 前端构建 → 定位 API 冒烟**
（精确匹配三段待检区段、校验错误码、无可行位置时的首条致空记录），并以退出码给出结果。

## 本地开发（无需 Docker、无需安装依赖）

```bash
python3 -m unittest discover -s tests -v     # 代码测试
python3 -m api.app.server                    # 启动 API（:8000，API_PORT 可改）
python3 web/build.py --out web/dist          # 前端构建
cd web/dist && python3 -m http.server 8080   # 任意静态服务器托管页面
# 端到端验证（需先启动本地 API 与静态服务）：
API_URL=http://localhost:8000 WEB_URL=http://localhost:8080 python3 -m verify.run
```

页面通过同源 `/api` 访问 API（Docker 中由 nginx 反代）；本地开发时
`python3 web/build.py --api-base http://localhost:8000/api` 可改写 API 基地址。

## API 契约

### `POST /api/locate`

```json
{
  "nodes": [1, 2, 3, 4],
  "edges": [{"u": 1, "v": 2, "length": "4"}, {"u": 2, "v": 3, "length": "4"}, {"u": 2, "v": 4, "length": "4"}],
  "speed": "1",
  "sensors": [
    {"id": "S1", "node": 1, "start": "9/2", "end": "11/2"},
    {"id": "S2", "node": 2, "start": "1/2", "end": "3/2"},
    {"id": "S3", "node": 3, "start": "5/2", "end": "11/2"}
  ]
}
```

- 长度、速度、到时均可为 JSON 数字或字符串（`"2.5"`、`"5/2"`），一律按**精确有理数**处理；
- 节点 4–12 个整数编号；边恰为 `节点数-1` 条且成树；传感器 3–6 台、不重复挂在同一节点。

**成功（200）**：每段给出 `position_from_u`（边上位置闭区间）、`mileage`（里程范围）、
`occurrence_time`（该段可共同成立的发生时刻范围），以及总范围；数值形如
`{"exact": "7/2", "decimal": 3.5}`。

```json
{
  "ok": true,
  "segment_count": 3,
  "segments": [
    {"edge_index": 0, "u": 1, "v": 2, "edge_length": {"exact": "4", "decimal": 4.0},
     "position_from_u": {"start": {"exact": "7/2", "decimal": 3.5}, "end": {"exact": "4", "decimal": 4.0}},
     "mileage": {"start": {"exact": "7/2", "decimal": 3.5}, "end": {"exact": "4", "decimal": 4.0}},
     "occurrence_time": {"start": {"exact": "1/2", "decimal": 0.5}, "end": {"exact": "3/2", "decimal": 1.5}},
     "includes_u": false, "includes_v": true}
  ],
  "occurrence_time": {"start": {"exact": "-7/2", "decimal": -3.5}, "end": {"exact": "3/2", "decimal": 1.5}}
}
```

**输入不可识别（400）** 与 **无可行位置（422）** 均返回结构化原因，页面据此清除旧报告并提示：

```json
{"ok": false, "error": {"code": "NO_FEASIBLE_POSITION", "message": "……加入第 3 台传感器 S3……后交集首次为空",
  "first_empty_sensor": "S3", "sensor_index": 3, "considered_sensors": ["S1", "S2", "S3"]}}
```

| 错误码 | 含义 |
| --- | --- |
| `INVALID_BODY` / `INVALID_NODES` / `INVALID_SENSORS` / `INVALID_NUMBER` | 请求结构或数值不可解析 |
| `NODE_COUNT` / `SENSOR_COUNT` | 节点 4–12、传感器 3–6 的数量约束 |
| `NOT_A_TREE` | 边数不为 n-1、成环、不连通、重复边、自环、引用未声明节点 |
| `NONPOSITIVE_LENGTH` / `NONPOSITIVE_SPEED` | 长度或速度不为正 |
| `SENSOR_DUPLICATE` | 传感器 id 重复或同一节点重复挂载 |
| `SENSOR_NODE_UNKNOWN` | 传感器挂在未声明节点 |
| `INTERVAL_INVERTED` | 到时区间起点大于终点 |
| `NO_FEASIBLE_POSITION` | 全部记录无法共同解释；附首条致空记录 |
