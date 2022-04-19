#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
./run_pytest.sh
./run_mypy.sh
./run_flake8.sh 
