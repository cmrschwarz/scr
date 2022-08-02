#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
pip-upgrade --skip-package-installation requirements_dev.txt
