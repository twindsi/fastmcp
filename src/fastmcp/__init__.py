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
"""

from fastmcp.server import FastMCP
from fastmcp.resources import Resource
from fastmcp.tools import Tool
from fastmcp.prompts import Prompt
from fastmcp.exceptions import FastMCPError

__version__ = "0.1.0"
__author__ = "FastMCP Contributors"

__all__ = [
    "FastMCP",
    "Resource",
    "Tool",
    "Prompt",
    "FastMCPError",
    "__version__",
]
