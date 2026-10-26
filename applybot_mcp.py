"""Start ApplyBot's MCP server (for Claude Desktop / Claude Code). Works from any working directory.

Uses config.yaml next to this file unless APPLYBOT_CONFIG is set."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("APPLYBOT_CONFIG", str(HERE / "config.yaml"))

from applybot.mcp_server import main  # noqa: E402

main()
