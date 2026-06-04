"""CLI entrypoint: ingest, serve, and install subcommands."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import fetch, ingest, install, server, store


def _embedder_or_none(no_embeddings: bool):
    if no_embeddings:
        return None
    from .embed import FastEmbedEmbedder

    print(
        "embedding controls (first run downloads ~130 MB to ~/.cache/fastembed)...",
        file=sys.stderr,
    )
    return FastEmbedEmbedder()


def _wipe_if_fresh(db_path: Path, fresh: bool) -> None:
    if fresh and db_path.exists():
        db_path.unlink()
        print(f"removed existing database at {db_path} (--fresh)", file=sys.stderr)


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path = Path(args.db or server.DEFAULT_DB)
    _wipe_if_fresh(db_path, args.fresh)
    oscal_dir = Path(args.oscal) if args.oscal else fetch.DEFAULT_CACHE
    if args.fetch:
        print("fetching OSCAL mirror...", file=sys.stderr)
        oscal_dir = fetch.ensure_clone(cache=oscal_dir)
    print(f"writing to {db_path}", file=sys.stderr)
    conn = store.open_db(db_path)
    vmeta, controls = ingest.load_version_from_dir(oscal_dir)
    print(f"parsed {len(controls)} controls for {vmeta.version}", file=sys.stderr)
    embedder = _embedder_or_none(args.no_embeddings)
    result = ingest.ingest_version(conn, vmeta, controls, embedder=embedder)
    conn.close()
    print(f"done. {result}", file=sys.stderr)
    return 0


def cmd_ingest_history(args: argparse.Namespace) -> int:
    db_path = Path(args.db or server.DEFAULT_DB)
    _wipe_if_fresh(db_path, args.fresh)
    repo_dir = Path(args.oscal_repo) if args.oscal_repo else fetch.DEFAULT_CACHE
    if args.fetch or not (repo_dir / ".git").is_dir():
        print("fetching OSCAL mirror...", file=sys.stderr)
        repo_dir = fetch.ensure_clone(cache=repo_dir)
    tags = fetch.list_tags(repo_dir)
    if args.from_tag:
        tags = [t for t in tags if t >= args.from_tag]
    if args.to_tag:
        tags = [t for t in tags if t <= args.to_tag]
    if not tags:
        print("no tags matched the range", file=sys.stderr)
        return 1
    conn = store.open_db(db_path)
    # Default policy: embed only the newest (active) version. --embed-all embeds every
    # version. --no-embeddings embeds none. Build the embedder once and choose per version.
    embedder = None if args.no_embeddings else _embedder_or_none(False)
    for i, tag in enumerate(tags):
        is_last = i == len(tags) - 1
        use = embedder if (args.embed_all or is_last) else None
        vmeta, controls = ingest.load_version_from_tag(repo_dir, tag)
        commit = fetch.current_commit(repo_dir, tag)
        ingest.ingest_version(
            conn,
            vmeta,
            controls,
            embedder=use,
            git_tag=tag,
            git_commit=commit,
            make_active=is_last,
        )
        print(f"  ingested {tag} ({len(controls)} controls)", file=sys.stderr)
    conn.close()
    print(f"done. {len(tags)} versions", file=sys.stderr)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    repo_dir = fetch.ensure_clone(
        cache=Path(args.oscal_repo) if args.oscal_repo else fetch.DEFAULT_CACHE
    )
    db_path = Path(args.db or server.DEFAULT_DB)
    conn = store.open_db(db_path)
    tags = fetch.list_tags(repo_dir)
    if not tags:
        print("no tags found", file=sys.stderr)
        return 1
    latest = tags[-1]
    vmeta, controls = ingest.load_version_from_tag(repo_dir, latest)
    embedder = _embedder_or_none(args.no_embeddings)
    ingest.ingest_version(
        conn,
        vmeta,
        controls,
        embedder=embedder,
        git_tag=latest,
        git_commit=fetch.current_commit(repo_dir, latest),
        make_active=True,
    )
    conn.close()
    print(f"done. active version {vmeta.version}", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ism-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Parse one OSCAL ISM release into the database.")
    p_ingest.add_argument("--oscal", help="Path to an OSCAL clone (default: managed cache).")
    p_ingest.add_argument("--db", help=f"Output database path (default: {server.DEFAULT_DB}).")
    p_ingest.add_argument("--fetch", action="store_true", help="Refresh the managed cache first.")
    p_ingest.add_argument(
        "--fresh", action="store_true", help="Wipe the database before ingesting."
    )
    p_ingest.add_argument(
        "--no-embeddings",
        action="store_true",
        help="skip embedding generation. Server falls back to lexical-only.",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_hist = sub.add_parser("ingest-history", help="Walk OSCAL git tags and ingest every release.")
    p_hist.add_argument("--oscal-repo", help="Path to an OSCAL clone (default: managed cache).")
    p_hist.add_argument("--db", help=f"Output database path (default: {server.DEFAULT_DB}).")
    p_hist.add_argument(
        "--from", dest="from_tag", help="Earliest tag to include (e.g. v2024.12.19)."
    )
    p_hist.add_argument("--to", dest="to_tag", help="Latest tag to include.")
    p_hist.add_argument("--fetch", action="store_true", help="Refresh the managed cache first.")
    p_hist.add_argument("--fresh", action="store_true", help="Wipe the database before ingesting.")
    p_hist.add_argument(
        "--embed-all", action="store_true", help="Embed every version, not just the newest."
    )
    p_hist.add_argument(
        "--no-embeddings", action="store_true", help="skip all embedding generation."
    )
    p_hist.set_defaults(func=cmd_ingest_history)

    p_update = sub.add_parser("update", help="Fetch and ingest the latest OSCAL release.")
    p_update.add_argument("--oscal-repo", help="Path to an OSCAL clone (default: managed cache).")
    p_update.add_argument("--db", help=f"Database path (default: {server.DEFAULT_DB}).")
    p_update.add_argument("--no-embeddings", action="store_true", help="skip embeddings.")
    p_update.set_defaults(func=cmd_update)

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
