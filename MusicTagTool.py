"""MusicTagTool entry point (PySide6 GUI).

Run with:  python MusicTagTool.py
"""
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main() -> int:
    # Qt 6 is High-DPI aware by default (disables scaling on Windows maps
    # physically), so the old Vista/Tk high-DPI rendering bugs don't apply.
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
