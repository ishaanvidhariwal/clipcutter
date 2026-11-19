#!/usr/bin/env bash
# ClipCutter setup for macOS and Linux. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf "\n\033[1;32m==>\033[0m %s\n" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  if ! have brew; then
    echo "Homebrew is needed first: https://brew.sh (then run this script again)"; exit 1
  fi
  say "Installing tools with Homebrew (uv, ffmpeg, node, fribidi)"
  for pkg in uv ffmpeg node fribidi; do
    brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
  done
elif [ "$OS" = "Linux" ]; then
  if have apt-get; then
    say "Installing tools with apt (needs sudo)"
    sudo apt-get update -y
    sudo apt-get install -y ffmpeg nodejs git libfribidi0 fonts-dejavu-core fonts-noto-color-emoji fonts-noto-core
  else
    echo "Please install ffmpeg, nodejs, libfribidi and the Noto fonts with your package manager."
  fi
  if ! have uv; then
    say "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

say "Installing Python packages (uv sync)"
uv sync

say "Checking everything"
uv run clipcutter doctor || true

printf "\nStart the app with:\n\n    uv run clipcutter serve\n\nthen open http://localhost:8787\n"
