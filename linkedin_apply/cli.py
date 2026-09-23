"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .answers import AnswerBank
from .config import ConfigError, load_config
from .search import build_search_url
from .tracker import Tracker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linkedin-apply", description=__doc__)
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config (default: config.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="open a browser to log in once; the session is saved")

    run = sub.add_parser("run", help="search and apply")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=None, help="fill forms but never submit")
    mode.add_argument("--live", action="store_true", help="really submit (overrides dry_run in config)")
    run.add_argument("--no-review", action="store_true", help="submit without asking y/n for each job")
    run.add_argument("--max", type=int, help="override limits.max_applications_per_run")
    run.add_argument("--headless", action="store_true", help="run the browser without a window")

    sub.add_parser("urls", help="print the search URLs the config produces")
    sub.add_parser("stats", help="summarise the application tracker")

    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    tracker = Tracker(cfg.files.tracker, cfg.files.unanswered)

    if args.command == "urls":
        for keyword in cfg.search.keywords:
            print(build_search_url(cfg.search, keyword))
        return 0

    if args.command == "stats":
        counts = tracker.summary()
        if not counts:
            print(f"No entries in {cfg.files.tracker} yet.")
        for status, n in sorted(counts.items()):
            print(f"{status:14} {n}")
        return 0

    from .bot import EasyApplyBot  # imported late so urls/stats work without Playwright

    if args.command == "login":
        EasyApplyBot(cfg, tracker, AnswerBank(cfg.answers, cfg.applicant)).login()
        return 0

    if args.live:
        cfg.behavior.dry_run = False
    elif args.dry_run:
        cfg.behavior.dry_run = True
    if args.no_review:
        cfg.behavior.review_before_submit = False
    if args.max is not None:
        cfg.limits.max_applications_per_run = args.max
    if args.headless:
        cfg.headless = True
    if cfg.headless and cfg.behavior.on_unknown_question == "ask":
        cfg.behavior.on_unknown_question = "skip"

    mode_text = "DRY RUN (nothing is submitted)" if cfg.behavior.dry_run else "LIVE"
    if not cfg.behavior.dry_run and cfg.behavior.review_before_submit:
        mode_text += ", asking before each submit"
    print(f"Mode: {mode_text}. Max applications: {cfg.limits.max_applications_per_run}")

    EasyApplyBot(cfg, tracker, AnswerBank(cfg.answers, cfg.applicant)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
