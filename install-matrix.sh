#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv="$project_dir/.venv"
revision="3da7a3bdfca4637bb79ff038bc2bb26965197db5"
repository="https://github.com/hzeller/rpi-rgb-led-matrix.git"

if [[ "$(uname -s)" != Linux ]] || [[ "$(uname -m)" != aarch64 && "$(uname -m)" != armv7l ]]; then
    echo "This installer requires a Raspberry Pi running 32-bit or 64-bit Linux." >&2
    exit 1
fi
if [[ "$(id -u)" == 0 ]]; then
    echo "Run this script as your normal Pi user, not with sudo; it will request sudo for apt." >&2
    exit 1
fi

sudo apt-get update
sudo apt-get install -y git build-essential cmake pkg-config python3-dev python3-venv

python3 -c 'import sys; sys.exit("Python 3.11 or newer is required") if sys.version_info < (3, 11) else None'
if [[ ! -e "$venv" ]]; then
    python3 -m venv "$venv"
elif [[ ! -x "$venv/bin/python" ]]; then
    echo "Existing $venv is not a usable Python virtual environment; resolve it before retrying." >&2
    exit 1
fi

"$venv/bin/python" -m pip install "git+$repository@$revision"
"$venv/bin/python" -c 'from rgbmatrix import RGBMatrix, RGBMatrixOptions; print("RGB matrix Python bindings installed successfully.")'

printf '\nMatrix bindings installed in %s\n' "$venv"
printf 'Install the remaining Touchline dependencies and run the application using this same Python.\n'
