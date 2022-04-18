#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
mypy --ignore-missing-imports scr
