#!/usr/bin/env python3
"""Deterministic frontend build: validate sources and emit a dist/ directory.

No network access or npm install is required.  When a Node.js runtime is
available it is used to syntax-check the JavaScript; otherwise a
structural sanity check is applied.  The build also renders ``config.js``
(API base URL) and a static ``health`` probe file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED = ("index.html", "app.js", "styles.css")


def _check_js_syntax(js_path: Path) -> str:
    node = shutil.which("node")
    if node:
        proc = subprocess.run(
            [node, "--check", str(js_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"前端构建失败: app.js 语法错误\n{proc.stderr.strip()}")
        return "node --check"
    # Fallback: delimiter balance (sources avoid unbalanced literals).
    text = js_path.read_text(encoding="utf-8")
    for open_ch, close_ch in (("{", "}"), ("(", ")"), ("[", "]")):
        if text.count(open_ch) != text.count(close_ch):
            raise SystemExit(f"前端构建失败: app.js 中 {open_ch}{close_ch} 数量不匹配")
    return "结构检查"


def build(src: Path, out: Path, api_base: str) -> None:
    problems = []
    for name in REQUIRED:
        if not (src / name).is_file():
            problems.append(f"缺少文件 {name}")
    if problems:
        raise SystemExit("前端构建失败:\n" + "\n".join(problems))

    html = (src / "index.html").read_text(encoding="utf-8")
    js = (src / "app.js").read_text(encoding="utf-8")
    css = (src / "styles.css").read_text(encoding="utf-8")

    for ref in ("app.js", "styles.css", "config.js"):
        if ref not in html:
            problems.append(f"index.html 未引用 {ref}")
    if "fetch(" not in js:
        problems.append("app.js 未包含 API 请求逻辑")
    if not html.strip().lower().startswith("<!doctype html>"):
        problems.append("index.html 缺少 DOCTYPE")
    if css.count("{") != css.count("}"):
        problems.append("styles.css 大括号不匹配")
    if problems:
        raise SystemExit("前端构建失败:\n" + "\n".join(problems))

    js_check = _check_js_syntax(src / "app.js")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in REQUIRED:
        shutil.copy2(src / name, out / name)
    (out / "config.js").write_text(
        "window.API_BASE = " + json.dumps(api_base) + ";\n", encoding="utf-8"
    )
    (out / "health").write_text("ok\n", encoding="utf-8")
    print(f"前端构建完成（JS 校验: {js_check}）：{len(REQUIRED) + 2} 个文件 -> {out}")


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="构建前端静态资源")
    parser.add_argument("--src", default=str(here / "src"), help="源目录")
    parser.add_argument("--out", default=str(here / "dist"), help="输出目录")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE_URL", "/api"),
        help="浏览器侧 API 基路径（默认 /api，由反向代理转发）",
    )
    args = parser.parse_args()
    build(Path(args.src), Path(args.out), args.api_base)


if __name__ == "__main__":
    main()
