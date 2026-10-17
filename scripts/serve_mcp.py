"""Launch local stdio MCP from any working directory. Does not load .env or start the API."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    try:
        from rw.mcp_server import main
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "mcp" or exc.name.startswith("mcp.")):
            print("MCP SDK is optional. Run sh scripts/setup.sh --mcp (PowerShell: scripts\\setup.ps1 -Mcp).",
                  file=sys.stderr)
            raise SystemExit(1) from None
        raise
    main()
