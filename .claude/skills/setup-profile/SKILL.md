---
name: setup-profile
description: Create or update the user's job-search profile (target titles, location, work arrangement, minimum salary, languages, each a must or a preference), with suggestions taken from their CV.
disable-model-invocation: true
allowed-tools: Read Write Bash(.venv/Scripts/job-analyzer *) Bash(.venv/bin/job-analyzer *)
---

# Set up the job-search profile (Claude Code mode, no API key needed)

The CLI is `.venv/Scripts/job-analyzer` on Windows and `.venv/bin/job-analyzer` on macOS/Linux.
Below it is written as `job-analyzer`. Run it from the repository root.

1. Run `job-analyzer spec cv-facts` and `job-analyzer spec profile`.

2. Read the CV (`data/cv.pdf`, `data/cv.txt` or `data/cv.md`). Following the cv-facts rules,
   work out suggestions: 3-5 job titles, 5-10 keywords, location, and languages with levels.
   If there's no CV, continue without suggestions.

3. Ask the user all five questions **in one message**, showing your suggestion for each and
   whether it's a must or a preference by default:
   1. Job titles + keywords (suggested from the CV)
   2. Where they want to work (suggested from the CV): must or preference? (default: preference)
   3. Work arrangements: remote / hybrid / onsite, must or preference? (default: must)
   4. Minimum salary: amount, currency, gross or net, per month or year, must or preference?
      (default: preference; it's fine to skip)
   5. Languages with levels (suggested from the CV): must or preference? (default: must)
   6. Job sites for `/find-jobs`: show the default global groups (company career pages, LinkedIn,
      remote job boards) and explain that the top job boards of each country they chose are
      researched automatically on the first `/find-jobs` run (and every ~3 months). Also ask how
      many postings to analyze per search (default 10).
   Then **wait for the answers**. Don't invent answers the user didn't give.

4. Write ONE JSON object for the profile to `data/inbox/profile.json`, following the profile
   spec. "must" → "hard", "preference" → "soft".

5. Validate and save: `job-analyzer import profile data/inbox/profile.json`
   If it prints `INVALID`, fix exactly the listed fields and import again.

6. Show the saved summary and say they can change it any time by running `/setup-profile` again.
