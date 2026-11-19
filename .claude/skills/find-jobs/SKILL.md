---
name: find-jobs
description: Search job sites for postings that match the user's profile and CV, analyze the best candidates in parallel, and return a ranked shortlist with links, fit, gaps and coverage. Use when the user asks to find, search for or look for jobs.
argument-hint: "[optional extra search terms]"
allowed-tools: Agent Read Write Bash(.venv/Scripts/job-analyzer *) Bash(.venv/bin/job-analyzer *)
---

# Find jobs (multi-agent, Claude Code mode)

You are the **coordinator**. You plan, delegate and assemble. Subagents search and read postings.
Code removes duplicates and ranks. Never re-rank or re-score by hand.

The CLI is `.venv/Scripts/job-analyzer` on Windows and `.venv/bin/job-analyzer` on macOS/Linux.
Extra search terms from the user: $ARGUMENTS

## 1. Load context
Run `job-analyzer plan` (JSON: site groups, countries to research, titles, keywords, locations,
work arrangements, max_postings). If it fails (no profile), tell the user to run `/setup-profile` and stop.

## 2. Country job boards (only when needed)
If `research_countries` is not empty, launch one **job-board-scout** per country, all in one
message. Give each one the country, the target titles, the `global_domains` and the output path
`data/inbox/boards/<country-slug>.json`. Each scout saves its boards to the profile itself.
Then run `job-analyzer plan` again. Tell the user at the end which boards were added
(they can edit them in `data/profile.json`).
If a scout fails, continue with the other groups and report the country under coverage gaps.

## 3. Plan the searches
Plan one **job-searcher** task per site group in `groups`. Spread the target titles and keywords
so that, **across the run, every target title is searched at least once**. A plan that only covers
one title is too narrow.

## 4. Search in parallel
Launch **all** job-searcher subagents **in one message** (parallel). Subagents see nothing of this
conversation, so give each one everything in its prompt:
site group name, its domains, the titles and keywords for this group, locations, work arrangements,
and the output path `data/inbox/search/<group-slug>.json`.

If a searcher ends without writing its file, write a `SearchBatch` for that group yourself, with
the failure in `errors`. Never drop a failed group silently.

## 5. Merge (code)
Run `job-analyzer merge <every output file>`. It validates the files and removes duplicates: the
same company + job title + date posted (a missing date counts as the same job). When a job appears
on several sites, it keeps the copy that can be read automatically and lists the others (e.g.
LinkedIn) as "also on". It also skips postings analyzed in earlier runs and picks up to
`max_postings` candidates round-robin across groups. If a file is `INVALID`, send the listed errors
back to that searcher once.

## 6. Analyze in parallel
Launch one **posting-analyst** per candidate, all **in one message** (in waves of at most 10).
Each prompt must contain:
- the full output of `job-analyzer brief`, verbatim
- the candidate's url, site, title and company
- the file prefix `data/inbox/analysis/<candidate id>`

## 7. Collect results
Each analyst replies with one JSON line. Write every `"status": "error"` line, as a JSON list, to
`data/inbox/analysis_errors.json`, so it shows up as a coverage gap. You may re-delegate a
`retryable` error once.

## 8. Shortlist (code)
Run `job-analyzer shortlist`. Present to the user:
- the top postings: title, company, date posted, overall score, link (plus "also on" links such
  as LinkedIn), fit summary, gaps and how to address them
- the excluded postings with their reason, in one line each
- the coverage gaps (failed searches, unreadable postings such as LinkedIn login walls)

Finish by offering `/analyze-job` for any posting the user wants to paste by hand.
