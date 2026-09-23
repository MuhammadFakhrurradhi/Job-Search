# LinkedIn Easy Apply automation

A semi-automated assistant for LinkedIn **Easy Apply** jobs. It searches with your filters,
skips jobs you don't want, fills in application forms from an answer bank you control, and
logs every job it handles in a CSV file.

> ⚠️ **Read this first.** LinkedIn's User Agreement prohibits bots and automated access, and
> LinkedIn can restrict or ban accounts that use them. This tool is built to keep you in
> control: it runs in **dry-run** mode by default, asks **y/N before every submit**, keeps a
> human pace with random delays, and caps applications per run. You are responsible for how you
> use it. Low volumes and careful review make sense for your account and for recruiters.

## How it works

```
search (keywords × filters) ──► job cards ──► title/company filters ──► open job
      ──► description filter ──► Easy Apply dialog ──► fill each step from answer bank
      ──► unknown required question?  ask you in the terminal  (or skip + log it)
      ──► review page: untick "Follow company" ──► dry run: discard  /  live: ask y/N ──► submit
      ──► write result to applications.csv
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

cp config.example.yaml config.yaml     # config.yaml is git-ignored — edit it
linkedin-apply login                   # log in manually once (2FA works); the session is saved
```

Your password is never stored. The logged-in browser session is saved in `.browser-profile/`
(git-ignored). Treat that folder like a password.

## Usage

```bash
linkedin-apply urls                    # print the search URLs your config produces
linkedin-apply run                     # dry run: fills forms, submits nothing
linkedin-apply run --live              # submit, asking y/N/q for each job
linkedin-apply run --live --max 5      # at most 5 submissions this run
linkedin-apply stats                   # counts by status from applications.csv
```

Other flags: `--no-review` (submit without asking, only after you trust your answer bank),
`--headless`, and `-c path/to/config.yaml`.

Recommended workflow:

1. Run a **dry run** or two and watch the browser.
2. Read `unanswered_questions.csv` and add rules for the recurring questions to `answers:` in
   `config.yaml`.
3. Switch to `--live` with review on, and keep `--max` small.

## Configuration

See [`config.example.yaml`](config.example.yaml); every option has a comment there. The main ones:

| Section     | Purpose |
|-------------|---------|
| `search`    | keywords, location, remote/hybrid/onsite, experience level, job type, date posted |
| `filters`   | regexes to include/exclude by title, exclude companies, exclude by description text |
| `limits`    | max applications per run, pages per search, random delays |
| `behavior`  | `dry_run`, `review_before_submit`, `on_unknown_question: ask/skip`, `unfollow_company` |
| `applicant` | contact details, optional resume upload, default years of experience |
| `answers`   | ordered `match` regex → `answer` rules; the first match wins |

How answers are chosen, in order:

1. Answers you typed in the terminal earlier in the same run.
2. The first `answers:` rule whose regex matches the question label.
3. Profile fields (first/last name, email, phone, city).
4. `default_years_experience` for "how many years…" questions.
5. `default_yes_no` for plain Yes/No choices, if you set it.

For dropdowns and radio buttons, the answer is matched to an option by exact text, then by
prefix, then by substring (`"Professional"` → `"Professional working proficiency"`). Numeric
fields get only the digits (`"IDR 15,000,000"` → `15000000`). Fields LinkedIn has already filled
in are left alone. Optional fields with no matching answer are left blank.

## Output files (all git-ignored)

- `applications.csv`: one row per job with status `applied`, `dry_run`, `skipped`, `failed` or
  `needs_answers`, plus the reason. Jobs that were `applied` or `skipped` are never revisited.
  The other statuses are retried on later runs.
- `unanswered_questions.csv`: required questions the answer bank couldn't handle, with their options.
- `screenshots/`: a screenshot of the page whenever an application fails.

## When LinkedIn changes its page layout

All CSS selectors live in the `SEL` dictionary at the top of
[`linkedin_apply/bot.py`](linkedin_apply/bot.py). If jobs start failing, look at the
screenshots, inspect the page, and update the selector that no longer matches.

## Development

```bash
pytest                                  # unit tests + browser tests against a mock Easy Apply dialog
CHROMIUM_PATH=/path/to/chrome pytest    # use a specific Chromium build for the browser tests
```
