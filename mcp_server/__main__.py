"""Bare `python -m mcp_server` entrypoint: stdio only, no subcommand, no flags."""

from mcp_server.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
