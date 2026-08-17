#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --extra inference --with pyinstaller pyinstaller --noconfirm --clean asr_workbench.spec
tar -C dist -czf dist/ASR-Workbench-linux.tar.gz ASR-Workbench
