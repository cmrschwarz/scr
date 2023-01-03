#!/usr/bin/env python


if not __package__:  # direct call of __main__.py
    import sys
    import os.path
    path = os.path.realpath(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(path)))

import scr

if __name__ == '__main__':
    scr.main()
