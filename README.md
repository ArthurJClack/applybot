# ApplyBot

An AI-assisted job and internship application system. It:

1. **Finds postings**: SimplifyJobs internship/new-grad lists, Greenhouse, Lever, Ashby, Remotive, RemoteOK, Arbeitnow, and optionally LinkedIn/Indeed via `python-jobspy`.
2. **Scores fit** against your profile (AI or keyword fallback) and filters by title, location, age, seniority and sponsorship.
3. **Tailors your resume and cover letter** from a plain-text file about you. It produces PDF, DOCX and Markdown, and a code-level guard blocks invented facts.
4. **Fills out and submits applications** in a real browser (Playwright) on almost any web form. It handles multi-step forms, file uploads, dropdowns, radios and custom questions, and saves new answers for next time.

Any AI provider works: OpenAI, Anthropic, Gemini, Ollama (local and free), any OpenAI-compatible API (Groq, OpenRouter, LM Studio…), any CLI command, or `none`.

## Desktop app (easiest)

Double-click **`dist\ApplyBot.exe`**. It opens ApplyBot in its own window with:

- **Dashboard**: stats, top matches, a setup checklist, and one-click *Run autopilot* / *Find jobs* / *Apply to a link*.
- **Jobs**: every posting found, with tabs, search, filters, bulk tailor/apply, and a details drawer showing the tailored résumé, cover letter and screenshots.
- **Apply to a link**: paste any application URL (job, internship, scholarship, program…).
- **Activity**: live progress. When ApplyBot needs you (review a submission, an unknown question, a CAPTCHA, a login), a dialog pops up and the window flashes.
- **Profile / Answers / Settings**: edit your info, standard answers, AI provider and key (with a *Test connection* button), job sources, and limits. No YAML editing needed.

The first time, click **Install** on the dashboard checklist to download the form-filling browser (~150 MB, once).

Your data lives in `Documents\ApplyBot` (or next to the .exe if a `config.yaml` is already there, for a portable setup; or any folder via `ApplyBot.exe --data <folder>`). Logs are at `%LOCALAPPDATA%\ApplyBot\applybot.log`.

From source, run `python main.py` (or `python main.py ui`, or double-click `ApplyBot.pyw`) to open the same UI using the current folder as the data folder.

To rebuild the exe: `powershell -ExecutionPolicy Bypass -File build_exe.ps1` (output: `dist\ApplyBot.exe`). LinkedIn/Indeed search via `python-jobspy` is only available when running from source.

To build a real installer (Start menu shortcut, optional desktop icon, uninstaller; installs per-user with no admin prompt): `powershell -ExecutionPolicy Bypass -File build_installer.ps1` (output: `dist\ApplyBot-Setup-<version>.exe`). Needs Inno Setup once: `winget install -e --id JRSoftware.InnoSetup`. Your data in `Documents\ApplyBot` is never touched by install or uninstall.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python main.py init        # creates config.yaml, profile.txt, answers.yaml, .env
```

Then:

1. Put **everything about you** in `profile.txt`: contact info, education, every job, project, skill and award. Use more than fits on one page, because ApplyBot picks the most relevant parts for each job. Use the `# Section` / `Title | Org | Dates` format from the template, or free text if an AI provider is configured.
2. Fill in `answers.yaml` with common application answers: work authorization, sponsorship, start date, salary, and optional EEO answers (defaults to "decline").
3. Choose an AI provider in `config.yaml` and put the key in `.env` (e.g. `OPENAI_API_KEY=...`). Use `provider: none` to run without AI.
4. Adjust `search` (keywords, locations, company slugs) and `apply` (mode, limits).

Check that your profile parsed correctly with `python main.py profile`.

## Usage

```powershell
python main.py search                 # fetch new postings from all enabled sources
python main.py score                  # rate fit 0-100 (status -> matched / rejected)
python main.py list --status matched  # browse matches
python main.py show <id>              # details for one job
python main.py tailor <id>            # write tailored resume + cover letter to output/
python main.py apply <id> --mode dry_run    # fill the form, don't submit, screenshot
python main.py apply <id>                   # review mode: you confirm before submit
python main.py apply --url <any application URL> --company X --title Y
python main.py run                    # search -> score -> tailor -> apply, end to end
python main.py run --mode auto --max 5 --headless
python main.py refresh                # search + score only (what the daily schedule runs)
python main.py schedule 08:45         # every morning: find + score new jobs (schedule --off to stop)
python main.py export                 # jobs.csv + applications.csv for your own spreadsheet
python main.py status                 # counts + recent applications
python main.py mark <id> applied      # manually set a status
python main.py mark <id> interviewing # track responses: interviewing / offer / rejected_by_company
python main.py ask "Why do you want to work here?"   # draft an answer from your profile
```

Use `-c path\to\config.yaml` to point at a different config.

### Apply modes

| mode | behavior |
|------|----------|
| `dry_run` | Fills everything, never submits, saves a screenshot. Use this to test. |
| `review` (default) | Fills everything, shows you the answers, and you type `y` to submit, `m` if you finished/submitted it yourself in the browser, or `n` to skip. Asks you for any required question it can't answer and remembers your answer. |
| `auto` | Submits on its own. If anything is uncertain (CAPTCHA, login wall, unanswerable required question) it marks the job `needs_review` instead of guessing. |

How a question gets answered: answers you saved earlier → your profile and `answers.yaml` → the AI (drafted from your profile only) → you. Questions about demographics, EEO, disability, veteran status, work authorization and legal consent are **never** sent to the AI. They come only from `answers.yaml` or from you.

## Adding companies

- Greenhouse: `boards.greenhouse.io/<token>` → add `<token>` to `search.sources.greenhouse.companies`
- Lever: `jobs.lever.co/<slug>` → `lever.companies`
- Ashby: `jobs.ashbyhq.com/<slug>` → `ashby.companies`

## Responsible use

- **No fabrication:** the tailoring step can only reorder, select and rephrase content from your profile. Bullets with new numbers, skills you didn't list, and changed titles or dates are rejected in code.
- **No bypassing protections:** CAPTCHAs and logins are handed to you (log in once in the persistent browser and the session is kept). ApplyBot does not solve CAPTCHAs.
- **Rate limits:** `max_per_run`, `max_per_day`, `max_per_company` (default 2 applications per company, ever) and random delays are on by default. Some sites (e.g. LinkedIn) forbid automation in their terms; it's your responsibility to follow each site's rules.
- Applying selectively to good-fit roles works better than mass-applying. Keep `min_score` meaningful and review what gets sent.

## Files

- `applybot/llm.py`: provider-agnostic AI wrapper
- `applybot/sources/`: job sources
- `applybot/matcher.py`: filtering and scoring
- `applybot/tailor.py`, `render.py`: resume and cover letter generation
- `applybot/answers.py`: question classification and answering
- `applybot/apply/`: browser form scanner and filler
- `applybot/ui/`: desktop UI (local web server, `static/` front end, `launcher.py` window and exe entry point)
- `ApplyBot.pyw`, `build_exe.ps1`, `tools/make_icon.py`: desktop launcher and exe build
- `output/<Company>_<Title>_<id>/`: per-job documents and screenshots
- `applybot.db`: SQLite tracker of jobs and applications

Run tests: `python -m pytest -q`

## Use it from Claude chat (MCP) - no API key needed

`applybot_mcp.py` exposes ApplyBot as an MCP server. Claude does the thinking (scoring, picking resume content) on
your Claude subscription; ApplyBot does the searching, truthful resume rendering and form filling.

1. `.venv\Scripts\pip install mcp`
2. Claude Desktop: Settings > Developer > Edit Config, add:
   ```json
   {"mcpServers": {"applybot": {
     "command": "C:\\Users\\you\\PycharmProjects\\ApplyBot\\.venv\\Scripts\\python.exe",
     "args": ["C:\\Users\\you\\PycharmProjects\\ApplyBot\\applybot_mcp.py"]}}}
   ```
   Claude Code: `claude mcp add applybot -- <path>\.venv\Scripts\python.exe <path>\applybot_mcp.py`
3. Restart Claude, then just ask: "search for new jobs, score the unscored ones, and tailor resumes for the top 3".

Tools: status, get_profile, search_jobs, list_jobs, get_job, set_score, tailor_resume, mark_job, apply_to_jobs.
`apply_to_jobs` defaults to dry_run; real submission needs mode=auto AND confirm_submit=true.
