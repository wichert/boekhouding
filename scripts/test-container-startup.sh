#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 IMAGE" >&2
    exit 2
fi

image="$1"
container="$(docker run --detach \
    --publish 127.0.0.1::8000 \
    --env AUDITLOG_XAF_PATH=data/auditlog-*.xaf \
    "$image")"

cleanup() {
    docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 30); do
    if [ "$(docker inspect --format '{{.State.Running}}' "$container")" = "false" ]; then
        docker logs "$container"
        echo "Container exited before becoming healthy." >&2
        exit 1
    fi

    port="$(docker port "$container" 8000/tcp | head -n 1 | sed 's/.*://')"
    if [ -n "$port" ] && curl --fail --silent "http://127.0.0.1:$port/health" | grep -q '"status":"ok"'; then
        echo "Container started successfully and /health returned ok."
        exit 0
    fi
    sleep 1
done

docker logs "$container"
echo "Container did not become ready within 30 seconds." >&2
exit 1
