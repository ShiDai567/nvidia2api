"""在构建镜像内验证真实 Nginx 的路由、慢请求和 SSE 转发，无需上游凭据。"""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/v1/slow":
            # 超过 Next.js rewrites 默认的 30 秒等待期限。
            time.sleep(31)
        if self.path == "/v1/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            time.sleep(1)
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = json.dumps({"path": self.path, "target": "backend"}).encode()
        self.send_response(400 if self.path == "/v1/error" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        payload = self.rfile.read(int(self.headers["Content-Length"]))
        assert self.headers.get("Authorization") == "Bearer local-proxy-test"
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class Frontend(Backend):
    def do_GET(self):
        payload = b"frontend"
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def fetch(path, **kwargs):
    return urllib.request.urlopen("http://127.0.0.1:3000" + path, timeout=40, **kwargs)


def check_stream():
    started = time.monotonic()
    request = urllib.request.Request(
        "http://127.0.0.1:3000/v1/stream", headers={"Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get("Content-Encoding") is None
        assert response.readline() == b"data: first\n"
        first_chunk_seconds = time.monotonic() - started
        assert first_chunk_seconds < 0.8, first_chunk_seconds
        assert b"data: [DONE]" in response.read()
    print("SSE 首片即时到达，后续分片完整，无 gzip 缓冲", flush=True)


def check_slow():
    with fetch("/v1/slow") as response:
        assert response.status == 200
        assert json.load(response)["target"] == "backend"
    print("等待 31 秒的 API 请求返回 200，未经过 Next.js 的 30 秒反代超时", flush=True)


def main():
    servers = [ThreadingHTTPServer(("127.0.0.1", 8000), Backend),
               ThreadingHTTPServer(("127.0.0.1", 3001), Frontend)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    subprocess.run(["nginx", "-t"], check=True)
    nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with fetch("/health") as response:
                    assert json.load(response)["target"] == "backend"
                break
            except urllib.error.URLError:
                assert nginx.poll() is None, "Nginx 启动失败"
                assert time.monotonic() < deadline, "Nginx 启动超时"
                time.sleep(0.05)
        for path in ("/api", "/api/admin/settings?test=1", "/v1", "/v1/models"):
            with fetch(path) as response:
                assert json.load(response) == {"path": path, "target": "backend"}
        for path in ("/login", "/api-keys", "/_next/static/test.js"):
            with fetch(path) as response:
                assert response.read() == b"frontend", path
        request = urllib.request.Request(
            "http://127.0.0.1:3000/v1/chat/completions",
            data=b'{"messages":[]}',
            headers={"Authorization": "Bearer local-proxy-test", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.read() == b'{"messages":[]}'
        try:
            fetch("/v1/error")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert json.load(exc)["target"] == "backend"
        else:
            raise AssertionError("应保留后端 HTTP 400")
        print("API、页面、静态资源路由及请求体、鉴权头、错误状态转发通过", flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(check_stream), pool.submit(check_slow)]
            for future in futures:
                future.result()
    finally:
        nginx.terminate()
        nginx.wait(timeout=5)
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
