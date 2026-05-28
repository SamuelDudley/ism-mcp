"""CLI entrypoint: `ism-mcp ingest ...` and `ism-mcp serve`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import ingest, server, store


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path = Path(args.db or server.DEFAULT_DB)
    print(f"writing to {db_path}", file=sys.stderr)
    conn = store.open_db(db_path)
    store.reset(conn)

    xlsx_path = Path(args.xlsx)
    print(f"parsing {xlsx_path}", file=sys.stderr)
    controls = list(ingest.parse_xlsx(xlsx_path))
    print(f"  found {len(controls)} controls", file=sys.stderr)

    if args.pdf:
        pdf_path = Path(args.pdf)
        print(f"attaching PDF excerpts from {pdf_path} (this takes a minute)", file=sys.stderr)
        controls = ingest.attach_pdf_excerpts(controls, pdf_path)
        with_excerpts = sum(1 for c in controls if c.pdf_excerpt)
        print(f"  matched excerpts for {with_excerpts}/{len(controls)} controls", file=sys.stderr)
        store.set_meta(conn, "pdf_source", str(pdf_path))

    store.insert_controls(conn, controls)
    store.set_meta(conn, "xlsx_source", str(xlsx_path))
    if args.revision:
        store.set_meta(conn, "ism_revision", args.revision)
    conn.close()
    print(f"done. {len(controls)} controls in {db_path}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.db:
        os.environ["ISM_MCP_DB"] = args.db
    server.run()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ism-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Parse an ISM XLSX (+ optional PDF) into the local database.")
    p_ingest.add_argument("--xlsx", required=True, help="Path to the Cloud Controls Matrix XLSX.")
    p_ingest.add_argument("--pdf", help="Optional path to the ISM PDF for per-control text excerpts.")
    p_ingest.add_argument("--db", help=f"Output database path (default: {server.DEFAULT_DB}).")
    p_ingest.add_argument("--revision", help="Revision label to record (e.g. 2026-03).")
    p_ingest.set_defaults(func=cmd_ingest)

    p_serve = sub.add_parser("serve", help="Run the MCP server over stdio.")
    p_serve.add_argument("--db", help=f"Database path (default: {server.DEFAULT_DB}).")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
