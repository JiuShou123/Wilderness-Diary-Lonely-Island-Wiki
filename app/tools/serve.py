#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
荒野日记：孤岛 · 本地 Wiki 启动服务

用途：
    在项目根目录启动一个本地静态 HTTP 服务器，并自动用默认浏览器打开 Wiki 首页。
    关闭控制台窗口，或在窗口内按 Ctrl + C，即可停止服务。

用法：
    python app/tools/serve.py                 # 默认 8000 端口，启动后自动打开浏览器
    python app/tools/serve.py --port 9000     # 指定起始端口
    python app/tools/serve.py --no-browser    # 只启动服务，不打开浏览器
    python app/tools/serve.py --host 0.0.0.0  # 允许同一局域网内的其它设备访问

特性：
    * 端口被占用时自动向后寻找可用端口（最多尝试 50 个），不会启动失败；
    * 若目标端口上已经有本 Wiki 在运行，则直接打开浏览器，不重复启动；
    * 响应头统一关闭缓存，内容更新后刷新页面即可看到最新内容。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

# --------------------------------------------------------------------------
# 路径与常量
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))

ENTRY_FILE = os.path.join(PROJECT_ROOT, "app", "index.html")
MANIFEST_FILE = os.path.join(PROJECT_ROOT, "wiki", "manifest.json")
STATE_FILE = os.path.join(HERE, ".serve.pid")  # 记录正在运行的服务进程（供 --stop 使用）

APP_PATH = "/app/"
DEFAULT_PORT = 8000
PORT_SCAN_LIMIT = 50
SITE_MARKER = "荒野日记：孤岛"  # 用于识别「本 Wiki 是否已在运行」


# --------------------------------------------------------------------------
# 端口与探测
# --------------------------------------------------------------------------


def is_port_free(port: int, host: str) -> bool:
    """端口是否可以被本进程独占绑定（即当前空闲）。

    注意：Windows 与 Unix 对 SO_REUSEADDR 的语义不同——在 Windows 上设置它
    反而允许绑定已被占用的端口，导致检测失效，因此这里必须使用
    SO_EXCLUSIVEADDRUSE（或不做任何设置）。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_wiki_serving(port: int) -> bool:
    """探测本地端口上是否已经跑着本 Wiki（避免重复启动）。"""
    url = f"http://127.0.0.1:{port}{APP_PATH}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 忽略系统代理
    try:
        with opener.open(url, timeout=1.5) as resp:
            status = getattr(resp, "status", 0) or resp.getcode()
            body = resp.read(8192).decode("utf-8", "ignore")
        return status == 200 and SITE_MARKER in body
    except Exception:
        return False


def pick_port(preferred: int, host: str) -> int:
    """从 preferred 开始向后找一个空闲端口。"""
    for port in range(preferred, preferred + PORT_SCAN_LIMIT):
        if is_port_free(port, host):
            return port
    raise RuntimeError(
        f"从 {preferred} 起连续 {PORT_SCAN_LIMIT} 个端口都被占用，请先关闭占用端口的程序。"
    )


# --------------------------------------------------------------------------
# 运行状态记录 / 停止服务（供 --stop 与「停止Wiki.bat」使用）
# --------------------------------------------------------------------------


def write_state(pid: int, port: int) -> None:
    """记录当前服务进程，便于之后精确停止。"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            fh.write(f"{pid} {port}\n")
    except OSError:
        pass  # 记录失败不影响服务本身


def clear_state() -> None:
    try:
        if os.path.isfile(STATE_FILE):
            os.remove(STATE_FILE)
    except OSError:
        pass


def read_state():
    """读取 (pid, port)，文件缺失或损坏时返回 None。"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            pid_str, port_str = fh.read().split()
        return int(pid_str), int(port_str)
    except Exception:
        return None


def is_pid_listening(pid: int, port: int) -> bool:
    """确认该进程确实在监听该端口，避免误杀其它进程。"""
    if os.name != "nt":
        return True
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout
    except Exception:
        return False
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[3].upper() == "LISTENING" and fields[-1] == str(pid):
            if fields[1].endswith(f":{port}"):
                return True
    return False


def find_running_wiki():
    """在默认端口区间内查找正在提供本 Wiki 的进程。

    用于清理「没有留下状态记录」的实例（例如旧版本脚本启动的、或状态文件被删掉的）。
    通过 HTTP 内容识别本站，避免误杀其它占用同区间的程序。
    """
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout
    except Exception:
        return []

    found = []
    seen = set()
    for line in out.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[3].upper() != "LISTENING":
            continue
        try:
            port = int(fields[1].rsplit(":", 1)[1])
            pid = int(fields[-1])
        except (IndexError, ValueError):
            continue
        if pid in seen or not (DEFAULT_PORT <= port < DEFAULT_PORT + PORT_SCAN_LIMIT):
            continue
        seen.add(pid)
        if is_wiki_serving(port):
            found.append((pid, port))
    return found


def stop_server() -> int:
    targets = []
    seen = set()

    state = read_state()
    if state is not None:
        pid, port = state
        if is_pid_listening(pid, port):
            targets.append((pid, port))
            seen.add(pid)
        else:
            print(f"   记录中的服务进程（PID {pid}，端口 {port}）已不在运行。")
        clear_state()

    # 兜底：扫描默认端口区间，覆盖没有状态记录的实例
    for pid, port in find_running_wiki():
        if pid not in seen:
            targets.append((pid, port))
            seen.add(pid)

    if not targets:
        print("   没有发现正在运行的 Wiki 服务。")
        print()
        return 0

    failed = False
    for pid, port in targets:
        print(f"   正在停止服务（PID {pid}，端口 {port}）...")
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception as exc:
            print(f"   [错误] 停止失败：{exc}")
            failed = True
            continue

        released = False
        for _ in range(25):  # 等待端口释放（最多 5 秒）
            if is_port_free(port, "127.0.0.1"):
                released = True
                break
            time.sleep(0.2)

        if released:
            print("   已停止。")
        else:
            print(f"   [警告] 端口 {port} 仍被占用，请在任务管理器中手动结束该进程。")
            failed = True

    print()
    return 1 if failed else 0


# --------------------------------------------------------------------------
# HTTP 处理器
# --------------------------------------------------------------------------


class WikiHandler(http.server.SimpleHTTPRequestHandler):
    """静态文件服务：关闭缓存，并且只在出错时打印日志（避免 559 个页面刷屏）。"""

    server_version = "GuDaoWikiHTTP/1.0"
    protocol_version = "HTTP/1.1"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_request(self, code: object = "-", size: object = "-") -> None:
        try:
            status = int(code)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            status = 0
        if status >= 400:
            sys.stderr.write(f"    [{status}] {self.requestline}\n")
            sys.stderr.flush()


ThreadingHTTPServer = getattr(http.server, "ThreadingHTTPServer", None)
if ThreadingHTTPServer is None:  # Python < 3.7 兜底

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):  # type: ignore[no-redef]
        daemon_threads = True


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


def page_count() -> str:
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as fh:
            return str(json.load(fh).get("count", "?"))
    except Exception:
        return "?"


def print_banner() -> None:
    print("=" * 60)
    print("   荒野日记：孤岛 · 本地 Wiki")
    print("=" * 60)
    print(f"   项目目录 : {PROJECT_ROOT}")
    print(f"   页面数量 : {page_count()} 篇")
    print("-" * 60)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    # 让输出实时刷新（输出被重定向到管道/文件时也可见）
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="启动《荒野日记：孤岛》本地 Wiki 服务器")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"起始端口，默认 {DEFAULT_PORT}（被占用时自动向后顺延）",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址，默认 127.0.0.1（仅本机可访问）；改为 0.0.0.0 可供局域网其它设备访问",
    )
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器")
    parser.add_argument("--stop", action="store_true", help="停止正在运行的 Wiki 服务")
    args = parser.parse_args(argv)

    if args.stop:
        print()
        print("=" * 60)
        print("   荒野日记：孤岛 · 本地 Wiki —— 停止服务")
        print("=" * 60)
        return stop_server()

    print()
    print_banner()

    if not os.path.isfile(ENTRY_FILE):
        print(f"   [错误] 找不到入口文件：{ENTRY_FILE}")
        print("          请确认本脚本仍位于 app/tools/ 目录下。")
        print()
        return 1

    # 目标端口上已经跑着本 Wiki → 直接打开浏览器
    if not is_port_free(args.port, args.host) and is_wiki_serving(args.port):
        url = f"http://localhost:{args.port}{APP_PATH}"
        print(f"   Wiki 已经在运行，直接打开：{url}")
        print()
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    try:
        port = pick_port(args.port, args.host)
    except RuntimeError as exc:
        print(f"   [错误] {exc}")
        print()
        return 1

    handler = functools.partial(WikiHandler, directory=PROJECT_ROOT)
    try:
        httpd = ThreadingHTTPServer((args.host, port), handler)
    except OSError as exc:
        print(f"   [错误] 无法在端口 {port} 上启动服务：{exc}")
        print()
        return 1

    url = f"http://localhost:{port}{APP_PATH}"
    print(f"   访问地址 : {url}")
    if port != args.port:
        print(f"   （端口 {args.port} 已被其它程序占用，已自动改用 {port}）")
    print("-" * 60)
    print("   服务运行中 —— 关闭本窗口即可停止服务")
    print("   （也可在本窗口按 Ctrl + C，或双击项目根目录下的 停止Wiki.bat）")
    print("=" * 60)
    print()

    write_state(os.getpid(), port)

    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n   正在停止服务 ...")
    finally:
        httpd.server_close()
        clear_state()

    print("   服务已停止，再见！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
