# 海缆故障定位（多水听器到时联合解算）

海上风电场检修后，工程师把多处水听器的到时记录录入页面，系统在**树状海缆网络**上
联合求解**连续的故障位置**与**未知的故障发生时刻**，列出**所有**与全部记录共同成立
的待检管段——而不是给出一处未经证实的单点，避免把分叉管段上的同一回波误判为某个
最近传感器旁的断点。

## 方法要点

- 故障位置 `s` 在每条边上连续取值（`0 ≤ s ≤ L`），发生时刻 `t0` 未知；
  传感器 `i` 的到时满足 `t_i = t0 + d(x, n_i) / v`。树中路径唯一，故
  `d(x, n_i) = c_i ± s`，每条到时记录化为关于 `(s, v·t0)` 的一对线性不等式。
- 对每条边解析求出可行域（凸集）在位置轴与时刻轴上的投影，得到**闭区间**结果；
  同一边上相接的结果会被合并。**不做离散采样，也不只枚举节点。**
- 距离与时间全程使用 `fractions.Fraction` 做**精确有理数**运算；
  API 同时返回精确值（`exact`，整数或 `p/q`）与 6 位小数近似（`approx`）。
- 仅保留**全部**记录均可解释的区间；无可行位置时，按录入顺序逐条加入记录，
  **稳定**指出首条使交集为空的传感器记录。

## 快速开始

```bash
docker compose up --build
# 打开 http://localhost:8080
```

宿主端口可通过环境变量或 `.env`（见 `.env.example`）配置：

```bash
WEB_PORT=9090 API_PORT=9000 docker compose up --build
```

- Web 服务：`web/`（nginx 托管前端静态文件，并把 `/api` 反向代理到 API），
  健康检查 `GET /healthz`。
- API 服务：`api/`（FastAPI + uvicorn），健康检查 `GET /health`。

## 一次性校验（verify）

Compose 中的 `verify` 服务在 `api`、`web` 健康检查通过后自动执行：
后端代码测试（pytest）→ 前端构建（tsc + vite build）→ 定位 API 冒烟
（直连 API 与经 Web 代理两条链路），并以**退出码**给出结果：

```bash
docker compose --profile verify up --build --exit-code-from verify
echo $?   # 0 = 全部通过
```

## 输入规则（页面与服务端共同遵守）

| 项 | 规则 |
| --- | --- |
| 节点 | 4 ~ 12 个，标签唯一 |
| 边 | 恰好 `节点数 − 1` 条、连通（即树），长度为正数（米） |
| 传播速度 | 正数（m/s，全网统一） |
| 传感器 | 3 ~ 6 台，编号唯一、不重复挂在同一节点 |
| 到时区间 | 闭区间 `[下限, 上限]`（秒），下限 ≤ 上限 |

输入不合法时，页面**清除旧报告**并显示可识别的原因
（如 `NOT_A_TREE`、`INVALID_LENGTH`、`INVALID_SPEED`、
`DUPLICATE_SENSOR`、`INVALID_INTERVAL` 等）。

## API

### `POST /api/locate`

```json
{
  "nodes": ["N0", "N1", "N2", "N3", "N4", "N5"],
  "edges": [
    {"from": "N0", "to": "N1", "length": "1000"},
    {"from": "N0", "to": "N2", "length": "1000"},
    {"from": "N0", "to": "N3", "length": "1000"},
    {"from": "N0", "to": "N4", "length": "1000"},
    {"from": "N0", "to": "N5", "length": "1000"}
  ],
  "speed": "1000",
  "sensors": [
    {"id": "SA", "node": "N1", "arrival": ["11.3", "11.5"]},
    {"id": "SB", "node": "N2", "arrival": ["11.3", "11.5"]},
    {"id": "SC", "node": "N3", "arrival": ["11.3", "11.5"]}
  ]
}
```

数值既可给十进制字符串也可给 JSON 数字，一律按十进制精确解析。

**可行（200）**：`segments` 列出全部待检区段；每段给出所属边、距边两端点的
里程闭区间（`fromStart` / `fromEnd`）与可共同成立的故障发生时刻闭区间
（`occurrenceTime`）。上例返回 5 段：三条挂传感器的臂各 `[0, 100] m`，
两条未挂传感器的臂整条 `[0, 1000] m` 均无法排除。

```json
{
  "ok": true,
  "feasible": true,
  "segmentCount": 5,
  "segments": [
    {
      "edgeIndex": 0,
      "edge": {"from": "N0", "to": "N1", "length": {"exact": "1000", "approx": "1000"}},
      "fromStart": {"lo": {"exact": "0", "approx": "0"}, "hi": {"exact": "100", "approx": "100"}},
      "fromEnd": {"lo": {"exact": "900", "approx": "900"}, "hi": {"exact": "1000", "approx": "1000"}},
      "occurrenceTime": {"lo": {"exact": "103/10", "approx": "10.3"}, "hi": {"exact": "21/2", "approx": "10.5"}}
    }
  ]
}
```

**无可行位置（200）**：`culprit` 稳定指出首条使交集为空的传感器记录。

```json
{
  "ok": true,
  "feasible": false,
  "culprit": {"index": 2, "order": 3, "id": "SC", "node": "N2", "arrival": {"lo": {"exact": "100", "approx": "100"}, "hi": {"exact": "101", "approx": "101"}}},
  "message": "……第 3 条传感器记录（SC @ N2）加入后交集首次为空。"
}
```

**输入不合法（400）**：

```json
{"ok": false, "error": {"code": "INVALID_INTERVAL", "message": "传感器 SA 的到时区间倒置：……"}}
```

## 本地开发

```bash
# 后端
python3 -m venv .venv && .venv/bin/pip install -r api/requirements-dev.txt
cd api && ../.venv/bin/python -m pytest -q          # 代码测试
../.venv/bin/python -m uvicorn app.main:app --port 8000

# 前端（另开终端，/api 会代理到本机 8000）
cd web && npm ci && npm run dev                     # 或 npm run build
```

## 目录结构

```
├── compose.yaml          # api / web / verify（一次性校验，profile=verify）
├── api/                  # FastAPI 后端：精确求解器 + 校验 + 测试
│   ├── app/solver.py     #   连续位置 × 发生时刻的精确有理数求解
│   ├── app/model.py      #   输入解析与可识别错误
│   └── tests/
├── web/                  # Vite + TypeScript 前端（nginx 托管并反代 /api）
├── verify/Dockerfile     # 一次性校验镜像（python + node）
└── scripts/              # verify.sh（测试+构建+冒烟）与 smoke.py
```
