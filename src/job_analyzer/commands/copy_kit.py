"""`copy-kit`: build the copy-button page from the saved CV sections."""

import sys
import webbrowser

from job_analyzer.copykit import write_copy_kit
from job_analyzer.cv import cached_cv_details, find_cv, load_cv_details


def do_copy_kit(refresh: bool, open_page: bool, cache_only: bool = False) -> int:
    cv_path = find_cv()
    if cv_path is None:
        raise ValueError("No CV found. Save it as data/cv.pdf (or data/cv.txt).")
    if cache_only:
        details = cached_cv_details(cv_path)
        if details is None:
            print("NO_CACHE: CV sections not extracted yet (or the CV changed).", file=sys.stderr)
            return 3
        cached = True
    else:
        details, cached = load_cv_details(cv_path, refresh=refresh)
    print("Using saved CV sections (CV unchanged)." if cached else f"Read sections from {cv_path}.")
    print(f"  {len(details.experience)} jobs, {len(details.education)} education entries, "
          f"{len(details.certifications)} certifications")
    path = write_copy_kit(details, cv_path.name)
    print(f"Copy kit: {path.resolve()}")
    if open_page:
        webbrowser.open(path.resolve().as_uri())
    return 0
