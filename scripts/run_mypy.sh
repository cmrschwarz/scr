#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
printf "mypy: "
mypy --ignore-missing-imports scr
