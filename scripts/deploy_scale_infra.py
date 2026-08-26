"""Deploy GPU Docker image + MediaMTX 3-shard to production."""
import sys

import paramiko

HOSTS = [("87.192.230.208", 2222), ("192.168.0.101", 22)]
USER = "admin_root"
PASSWORD = "qazxsw123@!"

REMOTE = r"""
set -e
APP_DIR=/opt/camera
bash "$APP_DIR/deploy/setup-scale-infra.sh"
"""


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

    stdin, stdout, stderr = client.exec_command(
        f"sudo bash -s <<'EOF'\n{REMOTE}\nEOF",
        timeout=1200,
    )
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
