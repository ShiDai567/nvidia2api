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

docker run -d --name "$container" "$image"
attempt=0
while [ "$attempt" -lt 60 ]; do
    if docker exec "$container" python3 -c "import urllib.request; [urllib.request.urlopen(url, timeout=2).close() for url in ('http://127.0.0.1:8000/health', 'http://127.0.0.1:3000/login')]" >/dev/null 2>&1; then
        echo "镜像默认入口启动成功，后端健康检查和前端登录页均返回 HTTP 200"
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
