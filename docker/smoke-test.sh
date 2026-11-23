#!/bin/sh
set -eu

# 验证构建产物的默认入口和真实服务，不覆盖容器启动命令。
image=$1
container="nvidia2api-smoke-$$"
cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 1' TERM INT

entrypoint=$(docker image inspect "$image" --format '{{json .Config.Entrypoint}}')
if [ "$entrypoint" != '["/bin/sh","/app/start.sh"]' ]; then
    echo "镜像启动入口不正确：$entrypoint" >&2
    exit 1
fi

# 独立容器使用替身上游验证真实 Nginx；慢请求超过旧入口的 30 秒期限。
docker run --rm -i --ulimit nofile=16384:16384 --entrypoint python3 "$image" - < "$(dirname "$0")/proxy-test.py"

docker run -d --name "$container" "$image"
attempt=0
while [ "$attempt" -lt 60 ]; do
    if docker exec "$container" python3 -c "import urllib.request; [urllib.request.urlopen(url, timeout=2).close() for url in ('http://127.0.0.1:3000/health', 'http://127.0.0.1:3000/login')]" >/dev/null 2>&1; then
        docker exec "$container" python3 -c '
import urllib.error
import urllib.request
for path in ("/api/admin/settings", "/v1/models"):
    try:
        urllib.request.urlopen("http://127.0.0.1:3000" + path, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, (path, exc.code)
        assert "application/json" in exc.headers.get("Content-Type", ""), path
    else:
        raise AssertionError("未认证 API 应返回 401: " + path)
'
        echo "镜像默认入口启动成功，Nginx 页面、健康检查和 API 路由均通过"
        docker stop -t 10 "$container" >/dev/null
        exit_code=$(docker inspect "$container" --format '{{.State.ExitCode}}')
        [ "$exit_code" = 0 ] || exit 1
        exit 0
    fi
    if [ "$(docker inspect "$container" --format '{{.State.Running}}')" != true ]; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done

docker logs "$container"
echo "镜像默认入口启动检查失败" >&2
exit 1
