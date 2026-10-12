#!/usr/bin/env bash
set -euo pipefail
PARALLAX_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
node -e 'if(Number(process.versions.node.split(".")[0]) < 22) process.exit(1)' || { echo 'Node.js 22 or newer is required (24 LTS recommended).' >&2; exit 1; }
cd "$PARALLAX_ROOT/apps/api"
uv sync --frozen --group dev
cd "$PARALLAX_ROOT/apps/web"
npm ci --no-audit --no-fund
