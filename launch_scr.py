#!/usr/bin/bash

# convenience wrapper for debugging from within a set working directory

import sys
import os

# add this directory to the front of the module lookup path so we
# get our version of scr, not some pip installed one
sys.path.insert(1, os.path.dirname(__file__))

# this must come after the path insertion
from scr import scr  # nopep8

scr.main()
