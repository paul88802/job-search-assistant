"""Command line: argument parsing and friendly errors. The work lives in `commands/`.

  job-analyzer setup                 create or redo your profile (API mode)
  job-analyzer analyze <posting.txt> analyze a posting against your profile (API mode)
  job-analyzer copy-kit              page with copy buttons for your experience/education/certs

Claude Code mode (no API key; used by the skills and agents in .claude/):
  job-analyzer spec <kind>           print the shared rules + JSON schema
  job-analyzer import <kind> <file>  validate JSON written by Claude Code and store it
  job-analyzer plan                  search groups + countries whose job boards need research
  job-analyzer brief                 candidate brief to hand to subagents
  job-analyzer live <files...>       fetch open jobs from company boards + feeds (no AI)
  job-analyzer merge <files...>      validate + merge search results into an analysis queue
  job-analyzer next                  next candidates to analyze (replaces failed ones)
  job-analyzer shortlist             rank the latest run's postings
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import anthropic

from job_analyzer.commands.api_mode import do_analyze, do_setup
from job_analyzer.commands.copy_kit import do_copy_kit
from job_analyzer.commands.importing import do_import
from job_analyzer.commands.search_run import (
    do_brief,
    do_live,
    do_merge,
    do_next,
    do_plan,
    do_shortlist,
)
from job_analyzer.llm import ExtractionError
from job_analyzer.specs import SPECS, spec_text

__all__ = ["do_analyze", "do_brief", "do_copy_kit", "do_import", "do_live", "do_merge", "do_next", "do_plan",
           "do_setup", "do_shortlist", "main", "run_safely"]


def run_safely(action: Callable[[], object]) -> int:
    """Run a command and turn known errors into friendly messages."""
    try:
        result = action()
    except FileNotFoundError as e:
        print(f"File not found: {e.filename}", file=sys.stderr)
        return 1
    except (ExtractionError, ValueError) as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    except TypeError as e:
        # The SDK raises this before sending anything when no credentials are found.
        if "authentication method" not in str(e):
            raise
        print("No API key found. Set ANTHROPIC_API_KEY (see README).", file=sys.stderr)
        return 1
    # Most specific API errors first, the general ones last.
    except anthropic.AuthenticationError:
        print("Invalid API key. Check ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    except anthropic.RateLimitError:
        print("Rate limited by the API. Wait a minute and try again.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as e:
        print(f"API error {e.status_code}: {e.message}", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("Could not reach the API. Check your internet connection.", file=sys.stderr)
        return 1
    return result if isinstance(result, int) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Job Search Assistant powered by Claude.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create or redo your job-search profile (API mode)").set_defaults(
        run=lambda a: do_setup())

    p = sub.add_parser("analyze", help="Analyze one job posting (API mode)")
    p.add_argument("posting", type=Path, help="Text file containing the job posting")
    p.add_argument("--json", action="store_true", help="Print raw JSON instead of a report")
    p.set_defaults(run=lambda a: do_analyze(a.posting, a.json))

    p = sub.add_parser("copy-kit", help="Open a page with copy buttons for your CV sections")
    p.add_argument("--refresh", action="store_true", help="Re-read the CV even if unchanged")
    p.add_argument("--no-open", action="store_true", help="Don't open the page in a browser")
    p.add_argument("--cache-only", action="store_true",
                   help="Never call the API; fail with exit code 3 if the CV isn't extracted yet")
    p.set_defaults(run=lambda a: do_copy_kit(a.refresh, not a.no_open, a.cache_only))

    p = sub.add_parser("spec", help="Print the rules + JSON schema for a task (Claude Code mode)")
    p.add_argument("kind", choices=sorted(SPECS))
    p.set_defaults(run=lambda a: print(spec_text(a.kind)))

    p = sub.add_parser("import", help="Validate and store JSON written by Claude Code")
    p.add_argument("kind", choices=sorted(SPECS))
    p.add_argument("file", type=Path)
    p.add_argument("--url", help="job: link to the original posting (enables dedupe + provenance)")
    p.add_argument("--site", help="job: domain the posting was found on")
    p.add_argument("--job", dest="job_id", help="fit: the JOB_ID printed when the job was imported")
    p.set_defaults(run=lambda a: do_import(a.kind, a.file, a.url, a.site, a.job_id))

    sub.add_parser("brief", help="Print the candidate brief for subagents").set_defaults(
        run=lambda a: do_brief())
    sub.add_parser("plan", help="Print the search plan inputs for /find-jobs (JSON)").set_defaults(
        run=lambda a: do_plan())

    p = sub.add_parser("merge", help="Validate + merge search batches into an analysis queue")
    p.add_argument("files", type=Path, nargs="+")
    p.add_argument("--limit", type=int, help="Postings to analyze successfully (default: profile max_postings)")
    p.set_defaults(run=lambda a: do_merge(a.files, a.limit))

    p = sub.add_parser("live", help="Fetch open jobs from company job boards and feeds (no AI)")
    p.add_argument("search_files", type=Path, nargs="*", help="Search batches to discover company boards from")
    p.add_argument("--out", type=Path, default=None, help="Default: data/inbox/search/live-sources.json")
    p.set_defaults(run=lambda a: do_live(a.search_files, a.out))

    p = sub.add_parser("next", help="Next candidates to analyze, replacing failed ones (JSON)")
    p.add_argument("--wave", type=int, default=10, help="Max candidates per wave")
    p.set_defaults(run=lambda a: do_next(a.wave))

    p = sub.add_parser("shortlist", help="Rank the analyzed postings of the latest run")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--all", action="store_true", help="Rank every saved posting, not just the latest run")
    p.set_defaults(run=lambda a: do_shortlist(a.top, a.all))
    return parser


def main() -> int:
    # UTF-8 output, so names with diacritics print correctly on Windows consoles.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    return run_safely(lambda: args.run(args))


if __name__ == "__main__":
    sys.exit(main())
