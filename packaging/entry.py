"""The program PyInstaller freezes: axross-markdown's own command."""

import sys

from axross_markdown.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
