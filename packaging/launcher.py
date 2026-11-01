"""Startskript für das gebündelte Programm (PyInstaller)."""

import sys

from zotivity.desktop import entry

if __name__ == "__main__":
    sys.exit(entry())
