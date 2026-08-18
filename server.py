#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""南京城墙历史 · 公测落地页 + 反馈/公告 轻量服务（仅依赖 Python 标准库）。

说明
----
- 首页 index.html 提供顶部导航（首页 / 反映 / 公告）。
- 「反映」：用户提交问题，POST /api/feedback 把内容追加到同目录 feedback.json；
            同时 GET /api/feedback 返回全部反馈，所有人都能看到彼此的反映。
- 「公告」：GET /api/announcements 返回 announcements.json（版本改动说明）；
            当前项目网址由前端用 window.location.origin 实时展示（隧道每次变化都准确）。
- 不开放任意静态文件下载，避免误暴露项目内的数据文件（如 db.sqlite3）。

运行
----
    python server.py            # 默认 0.0.0.0:5000
    python server.py --port 8080
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_FILE = os.path.join(BASE_DIR, "feedback.json")
ANNOUNCEMENTS_FILE = os.path.join(BASE_DIR, "announcements.json")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_feedback(item):
    items = load_json(FEEDBACK_FILE, [])
    items.append(item)
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return items


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _serve_index(self):
        fp = os.path.join(BASE_DIR, "index.html")
        if not os.path.isfile(fp):
            self.send_error(404, "index.html not found")
            return
        with open(fp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._serve_index()
        elif path == "/api/feedback":
            self._send_json(load_json(FEEDBACK_FILE, []))
        elif path == "/api/announcements":
            self._send_json(load_json(ANNOUNCEMENTS_FILE, {}))
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/feedback":
            self._send_json({"error": "not found"}, 404)
            return
        raw = self._read_body()
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid json"}, 400)
            return
        content = (data.get("content") or "").strip()
        if not content:
            self._send_json({"error": "内容不能为空"}, 400)
            return
        name = (data.get("name") or "").strip() or "匿名"
        item = {
            "id": int(time.time() * 1000),
            "name": name[:30],
            "content": content[:1000],
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_feedback(item)
        self._send_json({"ok": True, "item": item}, 201)

    def log_message(self, *args):
        pass  # 安静日志，避免刷屏


def main():
    ap = argparse.ArgumentParser(description="南京城墙历史 公测落地页服务")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()

    if not os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"公测落地页已启动： http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()
