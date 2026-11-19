"""First-run setup: ask the user for their preferences, with defaults from their CV.

`ask` and `say` are parameters (default: input/print) so tests can script answers.
"""

import re
from collections.abc import Callable

from job_analyzer.models import CVFacts, LanguageRequirement, Place
from job_analyzer.profile import Priority, Profile, SalaryPreference

LEVELS = {"a1": "A1", "a2": "A2", "b1": "B1", "b2": "B2", "c1": "C1", "c2": "C2", "native": "native"}
ARRANGEMENTS = ("remote", "hybrid", "onsite")


# ---- Parsers: text the user typed -> clean values (raise ValueError on bad input) ----

def parse_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_places(text: str) -> list[Place]:
    """'Bucharest, Romania; Germany' -> [Bucharest/Romania, anywhere in Germany]."""
    places = []
    for chunk in text.split(";"):
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        if not parts:
            continue
        if len(parts) == 1:
            places.append(Place(city=None, country=parts[0]))
        elif len(parts) == 2:
            places.append(Place(city=parts[0], country=parts[1]))
        else:
            raise ValueError(f"Use 'City, Country' or 'Country', got: {chunk.strip()}")
    return places


def parse_arrangements(text: str) -> list[str]:
    items = [i.lower() for i in parse_list(text)]
    bad = [i for i in items if i not in ARRANGEMENTS]
    if bad or not items:
        raise ValueError(f"Choose from: {', '.join(ARRANGEMENTS)}")
    return items


def parse_languages(text: str) -> list[LanguageRequirement]:
    """'English C1, Romanian native, German' -> languages with levels (unknown if omitted)."""
    result = []
    for item in parse_list(text):
        words = item.split()
        level = LEVELS.get(words[-1].lower()) if len(words) > 1 else None
        name = " ".join(words[:-1]) if level else item
        result.append(LanguageRequirement(language=name.title(), level=level or "unknown"))
    return result


def parse_salary(text: str) -> SalaryPreference | None:
    """'4000 EUR net month' or '4.5k eur' -> SalaryPreference. Empty -> None."""
    words = text.lower().replace(",", "").split()
    if not words:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(k?)", words[0])
    if not match:
        raise ValueError("Start with the amount, e.g. '4000 EUR net month'")
    amount = float(match.group(1)) * (1000 if match.group(2) else 1)
    pref = SalaryPreference(minimum=amount)
    for w in words[1:]:
        if w in ("gross", "net"):
            pref.basis = w
        elif w in ("month", "monthly", "year", "yearly", "annual"):
            pref.period = "month" if w.startswith("month") else "year"
        elif re.fullmatch(r"[a-z]{3}", w):
            pref.currency = w.upper()
        else:
            raise ValueError(f"Didn't understand '{w}'. Example: 4000 EUR net month")
    return pref


# ---- Formatting: clean values -> default text shown to the user ----

def format_places(places: list[Place]) -> str:
    return "; ".join(str(p) for p in places)


def format_languages(langs: list[LanguageRequirement]) -> str:
    return ", ".join(str(l) for l in langs)


# ---- The interactive flow ----

def run_setup(
    cv: CVFacts | None,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> Profile:
    def question(text: str, default: str, parse: Callable):
        hint = f" [{default}]" if default else ""
        while True:
            answer = ask(f"{text}{hint}: ").strip() or default
            try:
                return parse(answer)
            except ValueError as e:
                say(f"  ! {e}")

    def priority(what: str, default: Priority) -> Priority:
        d = "m" if default == "hard" else "p"
        while True:
            answer = (ask(f"  Is {what} a must (m) or a preference (p)? [{d}]: ").strip().lower() or d)
            if answer in ("m", "p"):
                return "hard" if answer == "m" else "soft"
            say("  ! Type m or p")

    say("\nLet's set up your job search (one time; edit data/profile.json later).")
    say("Press Enter to accept the suggestion in [brackets].\n")
    if cv is None:
        say("(No CV found in data/, so there are no suggestions.)\n")

    p = Profile()
    p.target_titles = question("1. Job titles you're looking for (comma-separated)",
                               ", ".join(cv.suggested_titles) if cv else "", parse_list)
    p.keywords = question("   Keywords/skills to search for (comma-separated)",
                          ", ".join(cv.key_skills) if cv else "", parse_list)

    p.locations = question("2. Where do you want to work? (City, Country; Country)",
                           str(cv.location) if cv and cv.location else "", parse_places)
    if p.locations:
        p.location_priority = priority("location", "soft")

    p.work_arrangements = question("3. Accepted work arrangements (remote, hybrid, onsite)",
                                   "remote, hybrid", parse_arrangements)
    p.work_arrangement_priority = priority("work arrangement", "hard")

    p.salary = question("4. Minimum salary, e.g. '4000 EUR net month' (Enter to skip)", "",
                        parse_salary)
    if p.salary:
        p.salary.priority = priority("salary", "soft")

    p.languages = question("5. Languages you speak, with level (e.g. English C1, Romanian native)",
                           format_languages(cv.languages) if cv else "", parse_languages)
    if p.languages:
        p.language_priority = priority("languages", "hard")

    return p


def describe(p: Profile) -> str:
    label = {"hard": "must", "soft": "preference"}
    lines = [
        f"Titles:      {', '.join(p.target_titles) or '-'}",
        f"Keywords:    {', '.join(p.keywords) or '-'}",
        f"Location:    {format_places(p.locations) or 'anywhere'} ({label[p.location_priority]})",
        f"Arrangement: {', '.join(p.work_arrangements)} ({label[p.work_arrangement_priority]})",
        f"Salary:      {p.salary or 'no minimum'}"
        + (f" ({label[p.salary.priority]})" if p.salary else ""),
        f"Languages:   {format_languages(p.languages) or '-'} ({label[p.language_priority]})",
    ]
    return "\n".join(lines)
