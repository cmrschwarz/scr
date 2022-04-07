#!/bin/bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
pip install -e .
rm -rf ./dist/*
python3 -m build
./tests/test.py
python3 -m twine upload --verbose --repository pypi dist/*
