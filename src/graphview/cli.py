"""Command line: `graphview serve <path>` opens the viewer, `graphview mcp` runs the MCP
server, `graphview coverage <path> --questions file` measures what the search reaches."""

from __future__ import annotations

import argparse
import secrets
import sys
import threading
import webbrowser

from .config import ConfigError, load_config
from .http_api import make_server
from .service import GraphService


def start_viewer(service: GraphService, port: int = 0) -> str:
    """Start the HTTP server in a background thread; return the URL with its token."""
    token = secrets.token_urlsafe(24)
    server = make_server(service, token, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # The token travels in the fragment, which browsers never send to a server.
    return f"http://127.0.0.1:{server.server_address[1]}/#token={token}"


def _coverage(service: GraphService, args) -> int:
    from . import coverage

    try:
        questions = coverage.load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(f"graphview: cannot read the questions: {exc}", file=sys.stderr)
        return 2
    for node_type in args.probe:
        questions += coverage.probe_questions(service.graph, node_type, args.probe_limit)
    if not questions:
        print("graphview: nothing to ask: give --questions FILE and/or --probe TYPE", file=sys.stderr)
        return 2

    def progress(done: int, total: int) -> None:
        if done == total or done % 10 == 0:
            print(f"  {done}/{total}", file=sys.stderr)

    print(f"{len(questions)} questions", file=sys.stderr)
    report = coverage.run(service, questions, progress=progress)
    saved = coverage.save(service.config.sources, report)
    s = report["summary"]
    print(f"search mode: {s['mode']}", file=sys.stderr)
    for kind, (reached, total) in s["reach_by_type"].items():
        print(f"{kind}: {reached} of {total} ever retrieved ({total - reached} never)", file=sys.stderr)
    if s["with_expectation"]:
        print(f"expected text retrieved: {s['expected_retrieved']} of {s['with_expectation']} "
              f"(in the composed answer: {s['expected_in_answer']})", file=sys.stderr)
    print(f"saved to {saved}; the viewer now offers 'recall hits' under colour by", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphview", description=__doc__)
    parser.add_argument("command", choices=["serve", "mcp", "coverage"])
    parser.add_argument("path", nargs="?", help="vault folder or memory.json")
    parser.add_argument("--config", help="graphview.yaml")
    parser.add_argument("--port", type=int, default=0, help="viewer port (default: any free)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--mask", action="store_true",
                        help="mask personal data, whatever the config says (for screenshots)")
    parser.add_argument("--questions", nargs="*", default=[], metavar="FILE",
                        help="coverage: question files (.json, .jsonl, or text, one per line)")
    parser.add_argument("--probe", action="append", default=[], metavar="TYPE",
                        help="coverage: also ask one question per node of this type, made of its name")
    parser.add_argument("--probe-limit", type=int, default=300, metavar="N",
                        help="coverage: at most N probes per type, best connected first (default 300)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, args.path)
        if args.mask:
            config.masking = True
        service = GraphService(config)
    except ConfigError as exc:
        print(f"graphview: {exc}", file=sys.stderr)
        return 2

    if args.command == "coverage":
        return _coverage(service, args)

    if args.command == "mcp":
        from .mcp_server import run
        run(service, args.port)
        return 0

    try:
        url = start_viewer(service, args.port)
    except OSError as exc:
        print(f"graphview: cannot listen on port {args.port}: {exc}", file=sys.stderr)
        return 2
    stats = service.stats()
    print(f"{stats['nodes']} nodes, {stats['edges']} links", file=sys.stderr)
    for warning in stats["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    print(url, file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
