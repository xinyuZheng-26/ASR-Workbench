#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --extra inference --with pyinstaller pyinstaller --noconfirm --clean asr_workbench.spec
ditto -c -k --sequesterRsrc --keepParent dist/ASR-Workbench dist/ASR-Workbench-macos.zip
