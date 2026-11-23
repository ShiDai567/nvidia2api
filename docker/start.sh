#!/bin/sh

# 由 Docker 的 WORKDIR=/app 提供工作目录；仅使用 POSIX sh 语法。
backend_pid=
frontend_pid=
nginx_pid=

cleanup() {
    trap '' TERM INT
    for pid in "$nginx_pid" "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$nginx_pid" "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}

trap 'cleanup; exit 0' TERM INT

# Nginx 的客户端连接和上游连接都消耗描述符；尽量提高软上限。
if ! ulimit -n 16384; then
    echo "nvidia2api: 无法提高文件描述符上限，请为容器配置 nofile >= 16384" >&2
fi

nginx -t || exit 1

echo "nvidia2api: 使用独立启动脚本，执行数据库迁移"
python3 manage.py migrate || exit 1

python3 -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 &
backend_pid=$!

(cd frontend && exec env HOSTNAME=127.0.0.1 PORT=3001 node server.js) &
frontend_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

# POSIX wait 只能等待指定进程；轮询存活状态以发现任一服务退出。
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
    sleep 1
done

echo "nvidia2api: 服务已退出，停止其余进程" >&2
cleanup
exit 1
