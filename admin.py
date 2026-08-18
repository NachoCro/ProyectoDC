#!/usr/bin/env python3
import argparse
import logging

from admin_ui.app import app


class _SilencePollingEndpoints(logging.Filter):
    """Drop all werkzeug access logs — the console should only show daemon
    enrichment progress (which product is being enriched), not HTTP request
    noise. Access lines always look like ``addr - - [date] "METHOD ...``.
    Startup/server messages and errors are still shown."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "werkzeug":
            return " - - [" not in record.getMessage()
        return True


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("werkzeug").addFilter(_SilencePollingEndpoints())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Admin UI — PrestaShop (Flask dev server)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=5000, help="Port")
    parser.add_argument("--debug", action="store_true", help="Flask debug mode")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
