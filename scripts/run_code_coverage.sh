#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
pytest --cov-report xml:cov.xml --cov scr --cov-append 
