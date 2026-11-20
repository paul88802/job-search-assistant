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

## 5. Live sources (code)
Run `job-analyzer live <every search output file>`. Plain code, no AI:
- finds the company job boards (Greenhouse, Lever, Ashby) in the search results, adds new ones to
  the profile's `watch_boards`, and fetches **every open job** on all watched boards from their
  official APIs
- fetches the Remote OK API and the We Work Remotely feeds from `live_feeds`
- keeps jobs whose title matches the target titles, in an acceptable location, not too old
- saves each job's full text, so analysts don't need to fetch pages
It writes `data/inbox/search/live-sources.json`. A failed source is reported, not fatal.

## 6. Merge (code)
Run `job-analyzer merge <every search output file> data/inbox/search/live-sources.json`. Code
validates the files and builds the run:
- drops search hits whose company board is live but no longer lists them (**closed**)
- drops postings in other regions and postings older than 60 days
- removes duplicates (same company + job title + date posted; a missing date counts as the same
  job) and postings analyzed in earlier runs, keeping the readable copy and "also on" links
- puts **readable** postings in an analysis queue (round-robin across groups)
- puts postings that exist only on sites that block reading (LinkedIn, We Work Remotely, ...) on a
  **check-yourself list**; they are never sent to analysts
If a file is `INVALID`, send the listed errors back to that searcher once.

## 7. Analyze in waves (backfill)
Repeat, at most 3 times:
1. Run `job-analyzer next`. It returns JSON with `done` and `candidates`. Code decides how many
   are still needed: failed postings are replaced by the next ones in the queue.
2. If `done` is true, stop.
3. Launch one **posting-analyst** per candidate, all **in one message**. Each prompt must contain:
   - the full output of `job-analyzer brief`, verbatim
   - the candidate's url, site, title, company and today's date
   - its `text_file` if it has one (live jobs): the analyst reads it instead of fetching the page
   - the file prefix `data/inbox/analysis/<candidate id>`
4. Wait until every analyst of the wave has replied.
You don't need to record errors: each analyst writes `<prefix>-status.json`, and code reads them.

## 8. Shortlist (code)
Run `job-analyzer shortlist`. It also writes `data/shortlist.html` and opens it in the browser
(cards with fit, pay, applied status and links). Tell the user the page is open, then present:
- the top postings: title, company, date posted, overall score, link (plus "also on" links such
  as LinkedIn), fit summary, gaps and how to address them
- the excluded postings with their reason, in one line each
- the **check-yourself** list (links only)
- the coverage gaps (failed searches, unreadable or closed postings)

Finish by offering `/analyze-job` for any check-yourself posting the user pastes in.
