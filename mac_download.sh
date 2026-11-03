#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
strategy_python=''
for strategy_candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$strategy_candidate" >/dev/null 2>&1 && "$strategy_candidate" -c 'import sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,13) else 1)' 2>/dev/null; then
        strategy_python="$strategy_candidate"
        break
    fi
done
if [ -z "$strategy_python" ]; then
    echo '需要 Python 3.11–3.13，建议从 https://www.python.org/downloads/macos/ 安装 Python 3.12。'
    echo '安装后重新打开终端，再执行 bash mac_download.sh。无需安装Homebrew或修改系统Python。'
    exit 2
fi
printf '使用Python：%s\n' "$strategy_python"
"$strategy_python" -m venv .venv-local
.venv-local/bin/python -m pip install -r requirements.txt
echo '先检查本机BaoStock连接；失败时停止，不生成模拟数据包。'
.venv-local/bin/python download_local.py --diagnose-only
.venv-local/bin/python download_local.py "$@"
