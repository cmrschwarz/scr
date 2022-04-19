#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
flake8 scr && printf "\e[1;32mflake8: success\e[0m\n"
