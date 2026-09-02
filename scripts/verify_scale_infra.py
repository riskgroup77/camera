"""Verify GPU + MediaMTX shard deployment."""
import os
import sys

import paramiko

HOSTS = [("87.192.230.208", 2222), ("192.168.0.101", 22)]
USER = "admin_root"
PASSWORD = os.environ.get("CAMERA_DEPLOY_PASSWORD")
if not PASSWORD:
    sys.exit(
        "CAMERA_DEPLOY_PASSWORD muhit ozgaruvchisi ornatilmagan. "
        "Server paroli endi kodda saqlanmaydi - u git tarixiga tushib qolgan edi. "
        "Ishlatishdan oldin uni muhit ozgaruvchisi sifatida bering."
    )

CHECK = """
set -e
cd /opt/camera
echo "=== Git ==="
git -c safe.directory=/opt/camera rev-parse --short HEAD
echo "=== Shard env ==="
grep -E '^MEDIAMTX_SHARD' camera-api/.env || true
echo "=== Containers ==="
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'mediamtx|api-1' || true
echo "=== Shard APIs ==="
curl -sf -o /dev/null -w 'mediamtx-0 api: %{http_code}\n' http://127.0.0.1:9997/v3/paths/list
curl -sf -o /dev/null -w 'mediamtx-1 api: %{http_code}\n' http://127.0.0.1:9998/v3/paths/list
curl -sf -o /dev/null -w 'mediamtx-2 api: %{http_code}\n' http://127.0.0.1:9999/v3/paths/list
echo "=== Health ==="
curl -sf http://127.0.0.1:18080/health; echo
echo "=== GPU env ==="
docker exec camera-api-api-1 printenv FACE_RECOGNITION_GPU_ENABLED 2>/dev/null || true
echo "=== API startup ==="
docker logs camera-api-api-1 2>&1 | tail -6
"""


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for host, port in HOSTS:
        try:
            client.connect(host, port=port, username=USER, password=PASSWORD, timeout=25)
            break
        except Exception:
            continue
    else:
        return 1
    stdin, stdout, stderr = client.exec_command("bash -s", timeout=120)
    stdin.write(CHECK)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    if err.strip():
        print("STDERR:", err)
    client.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
