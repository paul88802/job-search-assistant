"""Where the user's private files live, independent of the folder you run the tool from.

Order:
  1. JOB_ANALYZER_DATA environment variable, if set
  2. <project>/data when running from a source checkout (pip install -e .)
  3. ./data in the current folder (fallback for other installs)

Paths are computed when needed (functions, not constants), so tests and
users can point the tool somewhere else at any time.
"""

import os
from pathlib import Path

ENV_VAR = "JOB_ANALYZER_DATA"


def data_dir() -> Path:
    if env := os.environ.get(ENV_VAR):
        return Path(env)
    project_root = Path(__file__).resolve().parents[2]
    if (project_root / "pyproject.toml").exists():
        return project_root / "data"
    return Path.cwd() / "data"


def profile_path() -> Path:
    return data_dir() / "profile.json"


def cv_details_cache() -> Path:
    return data_dir() / "cv_details.json"


def copy_kit_path() -> Path:
    return data_dir() / "copy-kit.html"


def jobs_dir() -> Path:
    return data_dir() / "jobs"


def inbox_dir() -> Path:
    """Scratch area where Claude Code writes JSON before it is validated and imported."""
    return data_dir() / "inbox"


def run_file() -> Path:
    """Metadata of the latest /find-jobs run (start time, candidate count)."""
    return inbox_dir() / "run.json"


def coverage_file() -> Path:
    """Search errors and per-site counts of the latest run (for 'coverage gaps')."""
    return inbox_dir() / "coverage.json"


def analysis_errors_file() -> Path:
    """Legacy: errors written by the coordinator (now read from status files instead)."""
    return inbox_dir() / "analysis_errors.json"


def analysis_dir() -> Path:
    """Working files of the posting analysts, including one `<id>-status.json` per posting."""
    return inbox_dir() / "analysis"


def live_dir() -> Path:
    """Full text of live jobs (`<id>.txt`), so analysts read files instead of fetching pages."""
    return inbox_dir() / "live"


def live_index_file() -> Path:
    """Which company boards were fetched live, and which job URLs are open on them."""
    return inbox_dir() / "live_index.json"


def manual_check_file() -> Path:
    """Postings only found on hard-to-read sites (e.g. LinkedIn): the user checks these."""
    return inbox_dir() / "manual_check.json"


def shortlists_dir() -> Path:
    return data_dir() / "shortlists"
