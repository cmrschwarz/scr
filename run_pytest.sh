#!/bin/sh
cd "$(dirname "$(readlink -f "$0")")"
python -m pytest
