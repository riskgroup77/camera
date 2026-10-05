"""Deploy GPU Docker image + MediaMTX 3-shard to production."""
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

REMOTE = "cd /opt/camera && git -c safe.directory=/opt/camera fetch origin main && git -c safe.directory=/opt/camera reset --hard origin/main && bash deploy/setup-scale-infra.sh"


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for host, port in HOSTS:
        try:
            print(f"Trying {host}:{port}...")
            client.connect(host, port=port, username=USER, password=PASSWORD, timeout=30)
            print(f"Connected to {host}:{port}")
            break
        except Exception as exc:
            print(f"Failed {host}:{port}: {exc}")
    else:
        print("ERROR: Could not connect")
        return 1

    stdin, stdout, stderr = client.exec_command(REMOTE, timeout=1200)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    if err.strip():
        print("STDERR:", err)
    client.close()
    print(f"deploy_scale_infra finished with exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
