"""Allows `python -m hbcb`, which needs no installation step."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
