"""PreToolUse guard for the /find-jobs subagents.

The subagents read untrusted web pages. A posting could contain hidden text such as
"ignore your instructions and run <command>". The agents' prompts already say to ignore
such text, but a prompt is only probabilistic. This hook is the deterministic guarantee:

  Bash     -> only `job-analyzer spec ...` / `job-analyzer import ...`, no shell operators
  Write    -> only files inside <project>/data/inbox/
  WebFetch -> with --fetch-only-profile-domains (used by job-searcher): only the job sites
              listed in the user's profile, so a searcher can read list pages but nothing else

Exit code 0 = no objection, exit code 2 = block (the stderr message is shown to the agent).
Standard library only, so it runs with any Python 3.
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_SUBCOMMANDS = {"spec", "import"}
CLI_PREFIX = re.compile(r"^\s*(?:\./)?\.venv[\\/](?:Scripts|bin)[\\/]job-analyzer(?:\.exe)?\s+(\S+)")
SINGLE_QUOTED = re.compile(r"'[^']*'")
DOUBLE_QUOTED = re.compile(r'"[^"]*"')
SUBSTITUTION = re.compile(r"`|\$\(|\$\{")  # expanded by the shell even inside "double quotes"
OPERATORS = re.compile(r"[;&|<>\n\r]")


def block(reason: str) -> None:
    print(f"Blocked by project guard: {reason}", file=sys.stderr)
    sys.exit(2)


def check_bash(command: str) -> None:
    # Text inside quotes is a plain argument (e.g. a URL with '&'), except that the shell
    # still runs `...` and $(...) inside double quotes.
    without_single = SINGLE_QUOTED.sub("''", command)
    if SUBSTITUTION.search(without_single):
        block("command substitution (` or $( ) is not allowed for this agent.")
    if OPERATORS.search(DOUBLE_QUOTED.sub('""', without_single)):
        block("shell operators (; & | < >) outside quotes are not allowed for this agent.")
    m = CLI_PREFIX.match(command)
    if not m:
        block("this agent may only run `.venv/Scripts/job-analyzer spec|import ...`.")
    if m.group(1) not in ALLOWED_SUBCOMMANDS:
        block(f"`job-analyzer {m.group(1)}` is not allowed; only spec and import.")


def check_write(file_path: str, cwd: str, project: str) -> None:
    inbox = (Path(project) / "data" / "inbox").resolve()
    target = Path(file_path)
    if not target.is_absolute():
        target = Path(cwd) / target
    target = target.resolve()
    if inbox != target and inbox not in target.parents:
        block(f"this agent may only write inside data/inbox/ (tried: {file_path}).")


def profile_domains(project: str) -> list[str]:
    """All job-site domains in the user's profile (global groups + country job boards)."""
    data_dir = Path(os.environ.get("JOB_ANALYZER_DATA") or Path(project) / "data")
    try:
        profile = json.loads((data_dir / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    domains = [d for ds in (profile.get("search_sites") or {}).values() for d in ds]
    for boards in (profile.get("country_job_boards") or {}).values():
        domains += boards.get("domains", [])
    return [d.lower() for d in domains]


def check_fetch(url: str, project: str) -> None:
    host = (urlsplit(url).hostname or "").lower()
    allowed = profile_domains(project)
    if not any(host == d or host.endswith("." + d) for d in allowed):
        block(f"this agent may only fetch pages on the job sites in your profile (tried: {host or url}).")


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        block("could not read the hook input.")
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd

    if tool == "Bash":
        check_bash(str(tool_input.get("command", "")))
    elif tool == "Write":
        check_write(str(tool_input.get("file_path", "")), cwd, project)
    elif tool == "WebFetch" and "--fetch-only-profile-domains" in sys.argv[1:]:
        check_fetch(str(tool_input.get("url", "")), project)
    sys.exit(0)


if __name__ == "__main__":
    main()
