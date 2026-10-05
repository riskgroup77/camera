#!/usr/bin/env bash
# Install NVIDIA Container Toolkit on Ubuntu (GPU Docker for camera-api).
# Run on the production host as root: sudo bash deploy/install-nvidia-toolkit.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

echo "=== NVIDIA driver check ==="
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi not found — install NVIDIA drivers first, then re-run."
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

echo "=== NVIDIA Container Toolkit ==="
if command -v nvidia-ctk >/dev/null 2>&1; then
  echo "Already installed — reconfiguring Docker runtime"
else
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  apt-get install -y nvidia-container-toolkit
fi

nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo "=== Docker GPU smoke test ==="
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

echo "=== Done ==="
echo "Next: cd /opt/camera && sudo bash deploy/setup-scale-infra.sh"
