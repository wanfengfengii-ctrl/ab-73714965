# 一次性校验服务：代码测试 + 前端构建 + 定位 API 冒烟
# 运行结果以容器退出码给出（0 = 全部通过）。
FROM node:20-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# 预装后端依赖与测试工具（构建期缓存，运行期直接使用）
COPY api/requirements.txt api/requirements-dev.txt api/
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r api/requirements-dev.txt

# 预装前端依赖（构建期缓存，运行期执行真正的构建）
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci

COPY api/ api/
COPY web/ web/
COPY scripts/ scripts/

CMD ["bash", "scripts/verify.sh"]
