"""The shortlist as a local web page: one card per job, sortable, with your applications.

Built by plain code from the same data as the Markdown shortlist, not by Claude. Job postings
are untrusted text, so every value is HTML-escaped, and a link is only made clickable when it
is a plain http(s) URL (a `javascript:` link from a posting could otherwise run code).
"""

from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from job_analyzer import paths, tracker
from job_analyzer.ranking import Ranked, coverage_items, manual_candidates
from job_analyzer.tracker import Application


def _e(value) -> str:
    return escape(str(value), quote=True)


def safe_url(url: str | None) -> str | None:
    """Only http(s) links become clickable."""
    if not url:
        return None
    return url if urlsplit(url.strip()).scheme.lower() in ("http", "https") else None


def _link(url: str | None, label: str, cls: str = "btn") -> str:
    u = safe_url(url)
    if not u:
        return ""
    return f'<a class="{cls}" href="{_e(u)}" target="_blank" rel="noopener noreferrer">{_e(label)}</a>'


def _money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def _k(x: float) -> str:
    return f"{x / 1000:,.1f}k".replace(".0k", "k")


def _where(r: Ranked) -> str:
    j = r.record.job
    place = str(j.location) if j.location and (j.location.city or j.location.country) else ""
    policy = "" if j.remote_policy == "unknown" else j.remote_policy.capitalize()
    open_to = f"open to {', '.join(j.open_to)}" if j.open_to else ""
    return " · ".join(x for x in (place, policy, open_to) if x) or "Location not stated"


def _pay(r: Ranked) -> tuple[str, float | None]:
    """(HTML for the pay block, yearly net midpoint used for sorting)."""
    j, est = r.record.job, r.record.salary_estimate
    if j.salary is not None:
        return f'<div class="pay"><span class="tag">Stated</span> {_e(j.salary.raw_text)}</div>', None
    if est is None:
        return '<div class="pay muted">Pay not stated</div>', None
    y, n, cur = est.for_you, est.months_per_year, est.currency
    gross = "invoiced" if est.priced_as == "contractor" else "gross"
    net_lo, net_hi = y.net_monthly_low * n, y.net_monthly_high * n
    m = est.market
    sources = "".join(
        f"<li>{_link(s.url, s.name, 'plain') or _e(s.name)}: {_e(s.figure)}</li>" for s in est.sources)
    html = (
        f'<div class="pay"><span class="tag">Estimate · {_e(est.confidence)} confidence</span> '
        f'<strong>{_money(y.gross_monthly_low)}–{_money(y.gross_monthly_high)} {_e(cur)}/month {gross}</strong>'
        f' · net ≈ {_k(net_lo)}–{_k(net_hi)} {_e(cur)}/year'
        f'<details><summary>How this was estimated</summary>'
        f'<p><b>Contract:</b> {_e(est.priced_as)}{" (not stated)" if est.contract_type == "unknown" else ""}'
        f' · <b>Pay scale:</b> {_e(est.pay_market)}</p>'
        f'<p><b>Market for this role:</b> {_money(m.gross_monthly_low)}–{_money(m.gross_monthly_high)} '
        f'{_e(cur)}/month {gross}</p>'
        f'<p>{_e(est.reasoning)}</p><p class="muted">{_e(est.basis)}</p>'
        + (f"<ul>{sources}</ul>" if sources else "")
        + '<p class="muted">An estimate to prepare a salary conversation, not an offer.</p></details></div>'
    )
    return html, (net_lo + net_hi) / 2


STALE_DAYS = 60  # same age limit /find-jobs uses for new postings


def _age_days(posted: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(posted)).days if posted else None
    except ValueError:
        return None


def _card(rank: int, r: Ranked, app: Application | None, today: date) -> str:
    rec, j, fit = r.record, r.record.job, r.record.fit
    pay_html, pay_sort = _pay(r)
    fit_score = fit.fit_score if fit else None
    badges = []
    if app:
        badges.append(f'<span class="badge ok">✓ Applied {_e(app.applied_on or "(date unknown)")} · {_e(app.status)}</span>')
    if j.seniority != "unknown":
        badges.append(f'<span class="badge">{_e(j.seniority)}</span>')
    age = _age_days(j.posted_date, today)
    posted = (f"posted {j.posted_date} ({age} days ago)" if age is not None
              else f"posted {j.posted_date}" if j.posted_date else "posting date not shown")
    meta = f"{_e(_where(r))} · {_e(posted)} · found on {_e(rec.site or 'pasted')}"

    bars = []
    if fit_score is not None:
        bars.append(f'<div class="bar"><span>Fit</span><meter min="0" max="100" low="50" high="70" optimum="100" '
                    f'value="{fit_score}"></meter><b>{fit_score}</b></div>')
    bars.append(f'<div class="bar"><span>Preferences</span><meter min="0" max="100" low="50" high="70" '
                f'optimum="100" value="{r.report.score}"></meter><b>{r.report.score}</b></div>')
    if r.keyword_score is not None:
        bars.append(f'<div class="bar muted"><span>Keyword baseline</span><meter min="0" max="100" '
                    f'value="{r.keyword_score}"></meter><b>{r.keyword_score}</b></div>')

    detail = ""
    if fit:
        matches = "".join(f"<li>{_e(m)}</li>" for m in fit.matching_skills)
        gaps = "".join(f"<li>{_e(g)}</li>" for g in fit.gaps)
        detail = (
            '<details><summary>Matches, gaps and how to address them</summary><div class="cols">'
            + (f"<div><h4>Matches</h4><ul>{matches}</ul></div>" if matches else "")
            + (f"<div><h4>Gaps</h4><ul>{gaps}</ul></div>" if gaps else "")
            + "</div>"
            + (f'<p><b>How to address:</b> {_e(fit.how_to_address)}</p>' if fit.gaps else "")
            + "</details>"
        )
    flags = [c.detail for c in r.report.checks if c.outcome != "match"]
    if age is not None and age > STALE_DAYS and not app:
        flags.insert(0, f"Posted {age} days ago: check it's still open before applying")
    warn = "".join(f'<li class="chip">{_e(f)}</li>' for f in flags)
    red = "".join(f'<li class="chip red">{_e(f)}</li>' for f in j.red_flags)
    chips = f'<ul class="chips">{warn}{red}</ul>' if warn or red else ""

    actions = [_link(rec.source_url, "Open posting ↗", "btn primary")]
    if not app:
        actions.append(f'<button class="btn copy" data-track="{_e(rec.id)}">Copy “applied” command</button>')
    actions.append(f'<button class="btn copy" data-copy="{_e(rec.id)}">Copy JOB_ID</button>')

    return (
        f'<article class="card job" data-overall="{r.overall}" data-fit="{fit_score if fit_score is not None else -1}" '
        f'data-pay="{pay_sort if pay_sort is not None else -1}" data-posted="{_e(j.posted_date or "")}" '
        f'data-applied="{1 if app else 0}">'
        f'<header><span class="rank">#{rank}</span><div class="head"><h3>{_e(j.title)}</h3>'
        f'<div class="company">{_e(j.company or "Unknown company")}</div></div>'
        f'<div class="score" title="Overall: 60% fit + 40% preferences">{r.overall}</div></header>'
        f'<div class="meta">{meta}</div>'
        + (f'<div class="badges">{"".join(badges)}</div>' if badges else "")
        + f'<div class="bars">{"".join(bars)}</div>'
        + (f'<p class="summary">{_e(fit.summary)}</p>' if fit else '<p class="summary muted">Fit not assessed.</p>')
        + pay_html + chips + detail
        + f'<div class="actions">{"".join(a for a in actions if a)}</div></article>'
    )


def _applications(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty">No applications tracked yet. Use “Copy “applied” command” on a job, or tell Claude.</p>'
    cards = []
    for a in rows:
        history = "".join(
            f"<li>{_e(h['on'] or 'date unknown')}: {_e(h['status'])}" + (f" — {_e(h['note'])}" if h["note"] else "")
            + "</li>" for h in a["history"])
        cards.append(
            f'<article class="card app {_e(a["status"])}"><header><div class="head"><h3>{_e(a["title"])}</h3>'
            f'<div class="company">{_e(a["company"] or "?")}</div></div>'
            f'<span class="badge status">{_e(a["status"].replace("_", " "))}</span></header>'
            f'<div class="meta">Applied {_e(a["applied_on"] or "(date unknown)")} · JOB_ID {_e(a["job_id"])}</div>'
            f'<p class="next">→ {_e(a["next_step"])}</p>'
            f'<details><summary>History</summary><ul>{history}</ul></details>'
            f'<div class="actions">{_link(a["url"], "Open posting ↗", "btn")}</div></article>')
    return "".join(cards)


def _simple_list(items: list[str]) -> str:
    return f'<ul class="list">{"".join(items)}</ul>' if items else '<p class="empty">Nothing here.</p>'


def build_page(included: list[Ranked], excluded: list[Ranked], today: date | None = None) -> str:
    today = today or date.today()
    apps = tracker.load_applications()
    cards = "".join(_card(i, r, apps.get(r.record.id), today) for i, r in enumerate(included, 1))
    app_rows = tracker.summary(today=today)
    excl = [
        f'<li><b>{_e(r.record.job.title)}</b> @ {_e(r.record.job.company or "?")} — '
        f'{_e("; ".join(r.report.exclusion_reasons))} {_link(r.record.source_url, "posting ↗", "plain")}</li>'
        for r in excluded]
    manual = [
        f'<li><b>{_e(c.title)}</b> @ {_e(c.company or "?")}'
        + (f' <span class="muted">({_e(c.location)})</span>' if c.location else "")
        + f' {_link(c.url, "open ↗", "plain")}</li>' for c in manual_candidates()]
    coverage = [f"<li>{_e(c)}</li>" for c in coverage_items()]
    kit = paths.copy_kit_path()
    kit_link = (f'<a class="btn" href="{_e(kit.name)}" target="_blank">Open copy kit ↗</a>'
                if kit.parent == paths.shortlist_page().parent and kit.exists() else "")
    applied = sum(1 for r in included if r.record.id in apps)

    tabs = [("jobs", f"Shortlist ({len(included)})"), ("apps", f"My applications ({len(app_rows)})"),
            ("excluded", f"Excluded ({len(excluded)})"), ("manual", f"Check yourself ({len(manual)})"),
            ("coverage", "Coverage")]
    nav = "".join(f'<button class="tab{" on" if i == 0 else ""}" data-tab="{k}">{_e(label)}</button>'
                  for i, (k, label) in enumerate(tabs))
    body = (
        f'<section id="jobs" class="panel on"><div class="toolbar">'
        f'<label>Sort <select id="sort"><option value="overall">Best match</option><option value="fit">Fit</option>'
        f'<option value="pay">Pay (net estimate)</option><option value="posted">Newest</option></select></label>'
        f'<label><input type="checkbox" id="hide-applied"> Hide applied</label></div>'
        f'<div id="job-list">{cards or "<p class=empty>No analyzed jobs. Run /find-jobs.</p>"}</div></section>'
        f'<section id="apps" class="panel">{_applications(app_rows)}</section>'
        f'<section id="excluded" class="panel"><p class="muted">These break one of your must-haves.</p>'
        f'{_simple_list(excl)}</section>'
        f'<section id="manual" class="panel"><p class="muted">Found on sites that block automated reading. '
        f'Open the link; paste the text into /analyze-job to get a fit score.</p>{_simple_list(manual)}</section>'
        f'<section id="coverage" class="panel"><p class="muted">What could not be searched or read.</p>'
        f'{_simple_list(coverage)}</section>'
    )
    return PAGE.format(generated=datetime.now().strftime("%d %b %Y, %H:%M"), count=len(included),
                       applied=applied, nav=nav, kit_link=kit_link, body=body)


def write_page(included: list[Ranked], excluded: list[Ranked], path: Path | None = None) -> Path:
    path = path or paths.shortlist_page()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_page(included, excluded), encoding="utf-8")
    return path


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Shortlist</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#667085; --line:#e4e7ec;
          --accent:#2f6fed; --accent-text:#fff; --ok:#12805c; --ok-bg:#e7f6ef; --warn-bg:#fff4e0;
          --warn:#8a5a00; --red-bg:#fdecec; --red:#b42318; --chip:#f2f4f7; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14161b; --card:#1d2027; --text:#e6e8ee; --muted:#9aa3b2; --line:#2c303a;
            --accent:#5b8cff; --accent-text:#0b1020; --ok:#3ccf91; --ok-bg:#16352a; --warn-bg:#3a2e14;
            --warn:#f5c26b; --red-bg:#3d1c1c; --red:#ff8a80; --chip:#262a33; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width:920px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
  nav {{ display:flex; gap:4px; flex-wrap:wrap; border-bottom:1px solid var(--line); margin-bottom:16px; }}
  .tab {{ border:0; background:none; color:var(--muted); font:inherit; padding:8px 12px; cursor:pointer;
         border-bottom:2px solid transparent; margin-bottom:-1px; }}
  .tab.on {{ color:var(--text); border-bottom-color:var(--accent); font-weight:600; }}
  .panel {{ display:none; }} .panel.on {{ display:block; }}
  .toolbar {{ display:flex; gap:16px; align-items:center; margin-bottom:12px; color:var(--muted); flex-wrap:wrap; }}
  select {{ font:inherit; padding:2px 6px; background:var(--card); color:var(--text); border:1px solid var(--line); border-radius:6px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:12px; }}
  .card header {{ display:flex; gap:12px; align-items:flex-start; }}
  .head {{ flex:1; min-width:0; }}
  .card h3 {{ font-size:17px; margin:0; overflow-wrap:anywhere; }}
  .company {{ color:var(--muted); }}
  .rank {{ color:var(--muted); font-weight:600; padding-top:2px; }}
  .score {{ font-size:20px; font-weight:700; background:var(--chip); border-radius:10px; padding:4px 10px; }}
  .meta {{ color:var(--muted); font-size:13px; margin:6px 0; }}
  .badges {{ display:flex; gap:6px; flex-wrap:wrap; margin:6px 0; }}
  .badge {{ font-size:12px; background:var(--chip); border-radius:999px; padding:2px 10px; }}
  .badge.ok {{ background:var(--ok-bg); color:var(--ok); font-weight:600; }}
  .bars {{ display:grid; gap:4px; margin:10px 0; max-width:420px; }}
  .bar {{ display:grid; grid-template-columns:130px 1fr 32px; gap:8px; align-items:center; font-size:13px; }}
  .bar b {{ text-align:right; }}
  meter {{ width:100%; height:10px; }}
  .summary {{ margin:8px 0; }}
  .pay {{ margin:8px 0; }}
  .tag {{ font-size:12px; color:var(--muted); border:1px solid var(--line); border-radius:6px; padding:1px 6px; margin-right:4px; }}
  .chips {{ list-style:none; padding:0; margin:8px 0; display:flex; flex-wrap:wrap; gap:6px; }}
  .chip {{ font-size:12px; background:var(--warn-bg); color:var(--warn); border-radius:8px; padding:2px 8px; }}
  .chip.red {{ background:var(--red-bg); color:var(--red); }}
  details {{ margin:8px 0; }} summary {{ cursor:pointer; color:var(--accent); }}
  details p, details ul {{ margin:6px 0; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  h4 {{ margin:8px 0 4px; font-size:14px; }}
  .actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
  .btn {{ display:inline-block; border:1px solid var(--accent); color:var(--accent); background:transparent;
         border-radius:8px; padding:5px 12px; font:inherit; font-size:13px; cursor:pointer; text-decoration:none; }}
  .btn.primary {{ background:var(--accent); color:var(--accent-text); }}
  .btn.done {{ border-color:var(--ok); background:var(--ok); color:var(--card); }}
  a.plain {{ color:var(--accent); }}
  .muted {{ color:var(--muted); }} .empty {{ color:var(--muted); }}
  .list li {{ margin:6px 0; }}
  .next {{ margin:6px 0; font-weight:500; }}
  .app.rejected, .app.withdrawn, .app.no_response {{ opacity:.65; }}
  .app.offer .status, .app.interviewing .status {{ background:var(--ok-bg); color:var(--ok); }}
  .hidden {{ display:none; }}
  @media (max-width:600px) {{ .cols {{ grid-template-columns:1fr; }} .bar {{ grid-template-columns:100px 1fr 28px; }} }}
</style>
</head>
<body>
<main>
  <h1>Job Shortlist</h1>
  <div class="sub"><span>Generated {generated} · {count} jobs · {applied} applied</span>{kit_link}</div>
  <nav>{nav}</nav>
  {body}
</main>
<script>
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {{
    document.querySelectorAll(".tab, .panel").forEach(x => x.classList.remove("on"));
    t.classList.add("on"); document.getElementById(t.dataset.tab).classList.add("on");
  }}));
  const list = document.getElementById("job-list");
  function sortJobs() {{
    const key = document.getElementById("sort").value;
    const cards = [...list.querySelectorAll(".job")];
    const val = c => key === "posted" ? (c.dataset.posted || "0") : Number(c.dataset[key]);
    cards.sort((a, b) => (val(a) < val(b) ? 1 : val(a) > val(b) ? -1 : 0));
    cards.forEach(c => list.appendChild(c));
  }}
  document.getElementById("sort").addEventListener("change", sortJobs);
  document.getElementById("hide-applied").addEventListener("change", e => {{
    list.querySelectorAll(".job").forEach(c => c.classList.toggle("hidden", e.target.checked && c.dataset.applied === "1"));
  }});
  function fallbackCopy(text) {{
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t);
    t.select(); document.execCommand("copy"); t.remove();
  }}
  document.addEventListener("click", async (e) => {{
    const b = e.target.closest("button.copy");
    if (!b) return;
    const today = new Date().toLocaleDateString("sv-SE");  // YYYY-MM-DD
    const text = b.dataset.track
      ? `.venv\\\\Scripts\\\\job-analyzer track add ${{b.dataset.track}} --on ${{today}}`
      : b.dataset.copy;
    try {{ await navigator.clipboard.writeText(text); }} catch {{ fallbackCopy(text); }}
    const label = b.textContent; b.textContent = "Copied ✓"; b.classList.add("done");
    setTimeout(() => {{ b.textContent = label; b.classList.remove("done"); }}, 1200);
  }});
</script>
</body>
</html>
"""
