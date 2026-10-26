"""Double-click to open the ApplyBot desktop app (runs without a console window)."""
import sys

from applybot.ui.launcher import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
