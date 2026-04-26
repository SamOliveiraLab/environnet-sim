"""Web sandbox entry point.

Launch with:
    python -m environnets.web

Environment:
    ENVIRONNETS_HOST   bind host       (default 0.0.0.0)
    ENVIRONNETS_PORT   bind port       (default 8080)
    ENVIRONNETS_TITLE  page title      (default "EnvironNets Sandbox")
"""

import os
from environnets.web.app import build


def main():
    build()
    from nicegui import ui
    ui.run(
        host=os.environ.get("ENVIRONNETS_HOST", "0.0.0.0"),
        port=int(os.environ.get("ENVIRONNETS_PORT", "8080")),
        title=os.environ.get("ENVIRONNETS_TITLE", "EnvironNets Sandbox"),
        reload=False,
        show=False,
        favicon="\U0001F9EB",
    )


if __name__ == "__main__" or __name__ == "__mp_main__":
    main()
