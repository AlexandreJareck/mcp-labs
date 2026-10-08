"""MCP server entrypoint."""

import logging
import sys

from mcp.server import MCPServer

logger = logging.getLogger(__name__)

mcp = MCPServer("sqlite-consulta")


@mcp.tool()
def ping() -> str:
    """Return "pong" to confirm the server is reachable."""
    return "pong"


def main() -> None:
    """Start the server over stdio."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    logger.info("Starting sqlite-consulta over stdio")
    mcp.run()
