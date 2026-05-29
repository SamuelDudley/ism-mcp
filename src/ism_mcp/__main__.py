"""CLI entrypoint: `ism-mcp ingest ...` and `ism-mcp serve`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import ingest, install, server, store


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

    if args.no_embeddings:
        print("skipping embeddings (--no-embeddings)", file=sys.stderr)
    else:
        from .embed import FastEmbedEmbedder
        from .ingest import embed_controls

        print(
            "embedding controls (first run downloads ~130 MB to ~/.cache/fastembed)...",
            file=sys.stderr,
        )
        persisted = [store.get_control(conn, c.identifier) for c in controls]
        persisted = [c for c in persisted if c is not None]
        embedder = FastEmbedEmbedder()
        rows = list(embed_controls(persisted, embedder))
        store.insert_embeddings(conn, rows)
        print(f"embedded {len(rows)} controls", file=sys.stderr)

    conn.close()
    print(f"done. {len(controls)} controls in {db_path}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.db:
        os.environ["ISM_MCP_DB"] = args.db
    server.run()
    return 0


def _git_in_package(*git_args: str) -> str | None:
    pkg_dir = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(pkg_dir), *git_args],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError, FileNotFoundError:
        return None
    return out.stdout.strip() or None


def cmd_install(args: argparse.Namespace) -> int:
    project = Path(args.project)
    if not project.is_dir():
        print(f"error: --project {project} is not a directory", file=sys.stderr)
        return 1
    repo = args.repo or _git_in_package("remote", "get-url", "origin")
    rev = args.rev or _git_in_package("rev-parse", "--short", "HEAD")
    if args.mode == "uvx" and not repo:
        print(
            "error: uvx mode needs --repo. No git origin detected. "
            "Publish ism-mcp and set origin, or pass --repo.",
            file=sys.stderr,
        )
        return 1
    if args.mode == "docker" and not args.image:
        print("error: docker mode needs --image.", file=sys.stderr)
        return 1
    db_src = Path(args.db or server.DEFAULT_DB)
    try:
        actions = install.install(
            project=project,
            db_src=db_src,
            mode=args.mode,
            repo=repo,
            rev=rev,
            image=args.image,
            name=args.name,
            dry_run=args.dry_run,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    prefix = "would " if args.dry_run else ""
    for a in actions:
        print(f"  {prefix}{a}", file=sys.stderr)
    print(f"{'dry run, ' if args.dry_run else ''}done. {project}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ism-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser(
        "ingest", help="Parse an ISM XLSX (+ optional PDF) into the local database."
    )
    p_ingest.add_argument("--xlsx", required=True, help="Path to the Cloud Controls Matrix XLSX.")
    p_ingest.add_argument(
        "--pdf", help="Optional path to the ISM PDF for per-control text excerpts."
    )
    p_ingest.add_argument("--db", help=f"Output database path (default: {server.DEFAULT_DB}).")
    p_ingest.add_argument("--revision", help="Revision label to record (e.g. 2026-03).")
    p_ingest.add_argument(
        "--no-embeddings",
        action="store_true",
        help="skip embedding generation. Server falls back to lexical-only.",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_serve = sub.add_parser("serve", help="Run the MCP server over stdio.")
    p_serve.add_argument("--db", help=f"Database path (default: {server.DEFAULT_DB}).")
    p_serve.set_defaults(func=cmd_serve)

    p_install = sub.add_parser(
        "install",
        help="Write Claude Code config, guidance, manifest, and database into a repo.",
    )
    p_install.add_argument("--project", required=True, help="Target repo root.")
    p_install.add_argument(
        "--mode",
        choices=["uvx", "docker"],
        default="uvx",
        help="Distribution mode (default: uvx).",
    )
    p_install.add_argument(
        "--repo", help="Source git URL. Defaults to this checkout's origin remote."
    )
    p_install.add_argument(
        "--rev", help="Git revision to pin. Defaults to this checkout's short HEAD."
    )
    p_install.add_argument("--image", help="Docker image reference (docker mode).")
    p_install.add_argument("--db", help=f"Source database to copy (default: {server.DEFAULT_DB}).")
    p_install.add_argument("--name", default="ism", help="MCP server key name (default: ism).")
    p_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned writes without changing anything.",
    )
    p_install.set_defaults(func=cmd_install)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
