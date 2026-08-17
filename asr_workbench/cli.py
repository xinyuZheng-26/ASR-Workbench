"""Desktop-friendly local server entry point."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from .service import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动本地 ASR Workbench")
    parser.add_argument("--host", default="127.0.0.1", help="默认只允许本机访问")
    parser.add_argument("--port", type=int, default=8765, help="本地监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    arguments = parser.parse_args()
    if arguments.host != "127.0.0.1":
        parser.error("安全默认值要求 --host 只能是 127.0.0.1。")
    if not arguments.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d" % arguments.port)).start()
    uvicorn.run(create_app(), host=arguments.host, port=arguments.port, log_level="info")
