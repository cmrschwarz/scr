#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
pip install -e .
scr --help >/dev/null # make sure the installed script works
rm -rf ./dist/*
python3 -m build
./scripts/run_tests_local.sh
#./scripts/run_tox.sh
python3 -m twine upload --verbose --repository pypi dist/*
