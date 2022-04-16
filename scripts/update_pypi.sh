#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
pip install -e .
rm -rf ./dist/*
python3 -m build
./scripts/run_pytest.sh
tox
python3 -m twine upload --verbose --repository pypi dist/*
