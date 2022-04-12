#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
sed -i '/## Options List/q' README.md
echo '```' >> README.md
scr help >> README.md
echo '```' >> README.md
