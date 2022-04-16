#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
flake8 scr
