from __future__ import annotations

import argparse
import json
from pathlib import Path

from singing_app.harness.runner import HarnessRunner
from singing_app.runtime_check import checks_as_dicts


def run_job(args: argparse.Namespace) -> None:
    runner = HarnessRunner.from_file(Path(args.job), dry_run=args.dry_run)
    runner.run(resume=not args.no_resume)
    print(f"Job finished: {args.job}")


def show_status(args: argparse.Namespace) -> None:
    job_path = Path(args.job)
    with job_path.open("r", encoding="utf-8") as file:
        job_data = json.load(file)
    output_dir = Path(job_data["output_dir"])

    for name in ("state.json", "artifacts.json"):
        path = output_dir / name
        print(f"\n== {name} ==")
        if not path.exists():
            print("not found")
            continue
        print(path.read_text(encoding="utf-8"))


def launch_web(args: argparse.Namespace) -> None:
    from singing_app.web import run_web_server

    run_web_server(host=args.host, port=args.port, open_browser=not args.no_open)


def check_runtime(args: argparse.Namespace) -> None:
    checks = checks_as_dicts()
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return

    failed = False
    for check in checks:
        status = "OK" if check["ok"] else "MISSING"
        print(f"[{status}] {check['name']} - {check['message']} ({check['path']})")
        failed = failed or not bool(check["ok"])
    if failed:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI singing video workflow harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a harness job")
    run_parser.add_argument("--job", required=True, help="Path to a job JSON file")
    run_parser.add_argument("--dry-run", action="store_true", help="Validate flow without running heavy tools")
    run_parser.add_argument("--no-resume", action="store_true", help="Run from the first step even if state exists")
    run_parser.set_defaults(func=run_job)

    status_parser = subparsers.add_parser("status", help="Print job state and artifacts")
    status_parser.add_argument("--job", required=True, help="Path to a job JSON file")
    status_parser.set_defaults(func=show_status)

    web_parser = subparsers.add_parser("web", help="Launch the local browser web UI")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    web_parser.add_argument("--port", type=int, default=7860, help="Port to bind")
    web_parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    web_parser.set_defaults(func=launch_web)

    runtime_parser = subparsers.add_parser("check-runtime", help="Check local app runtime")
    runtime_parser.add_argument("--json", action="store_true", help="Print checks as JSON")
    runtime_parser.set_defaults(func=check_runtime)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

