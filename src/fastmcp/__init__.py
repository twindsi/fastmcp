"""FastMCP - A fast, Pythonic Model Context Protocol server framework.

This is a fork of PrefectHQ/fastmcp with additional features and improvements.

Basic usage:
    from fastmcp import FastMCP

    mcp = FastMCP("My Server")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    if __name__ == "__main__":
        mcp.run()

Note: Also exposes __version__ for easy version checking via fastmcp.__version__
"""

from fastmcp.server import FastMCP
from fastmcp.resources import Resource
from fastmcp.tools import Tool
from fastmcp.prompts import Prompt
from fastmcp.exceptions import FastMCPError

__version__ = "0.1.0"
__author__ = "FastMCP Contributors"

# Expose version info as a tuple for easier programmatic comparisons
# e.g. if fastmcp.VERSION_INFO >= (0, 2, 0): ...
VERSION_INFO = tuple(int(x) for x in __version__.split("."))

__all__ = [
    "FastMCP",
    "Resource",
    "Tool",
    "Prompt",
    "FastMCPError",
    "__version__",
    "VERSION_INFO",
]
