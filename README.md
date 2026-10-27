# Dreams into Reality

## Creator

This project was created, written, and maintained by **Anish Kumar**.

Dreams into Reality turns a **syllabus or career goal** into a realistic study plan. You give the number of days you have and the hours you can study per day; the app builds a roadmap with dated tasks, weekly capacity, buffer, and progress tracking. For UPSC, it adds prelims/mains practice, full mocks, interview prompts, and a free materials hub.

The practice and assessment pipeline is **zero-cost**: it uses **previous-year questions (PYQs) fetched from public open-source archives**, validated locally, cached in the database, and served without an LLM or paid API.

## What it does

- Plans by **days available + hours per day + study days per week**, with intensity modes, weekday-aware due dates, capacity checks, buffer, and automatic extension when the workload does not fit.
- **Understands natural-language plans.** Describe it in one sentence — "BCA semester 4 exam in 30 days, 3 hours daily, subjects: DBMS, OS, Python" — and the planner fills the goal, plan type, timeline, daily hours, study days, level, focus areas, and topics. Parsing is deterministic regex logic with no model or paid API, and fields you already edited are left untouched.
- Parses pasted syllabi or PDF/TXT/DOCX/image uploads into topics and creates chunked tasks with difficulty and hour estimates. Extraction is section-aware: it keeps Unit/Module/Chapter topics and inline topic lists, while skipping course objectives, outcomes, credits, marks, attendance rules, textbooks, references, page numbers, and institution headers. Course-code lines, module-only headings, objective sentences, and duplicate topics are dropped, and the preview reports how many lines were filtered.
- **Review and edit topics before and after creation.** Uncheck a topic to exclude it, remove it, add missing modules, bulk-edit one per line, drag to reorder, or run Clean & Trim. Editing an existing plan rebuilds only unfinished tasks and reschedules them from today; completed tasks, hours, and evidence are preserved.
- **Generates a full prep plan from a career role alone.** Type "Marine Biologist", "Data Analyst", or "Product Designer" and the app classifies the role into a career family and builds topics, projects, assignments, a toolkit, and a target outcome — no syllabus or file needed. Roles are mapped through 15 families (software, data, design, product, marketing, business, healthcare, education, legal, engineering, public service, operations, science, hospitality, general), each producing ~12 topics, 4–5 projects, 5–6 assignments, tools, and an outcome statement. Assignments and projects become tracked tasks with hour estimates.
- Provides a dedicated **UPSC mission** with subject selection, official resources, weekly assessments, prelims practice, mains questions with rule-based answer frameworks, interview prompts, and a materials hub.
- Serves **randomized PYQ tests** from a local cache:
  - Prelims: verified UPSC CSE years 2015 and 2017–2023.
  - Prelims open-archive practice: 2016 and 2024, clearly labelled because their keys are not officially verified; no negative marking is applied.
  - Mains: GS-I, GS-II, and GS-III (2013–2021) with original rule-based scaffolding, never invented model answers.
  - Full prelims mock: 100 questions with year spreading and UPSC marking (+2 / −0.66).
  - Weak-topic retest: after a test, missed topics become a fresh targeted paper.
- Scores every test **server-side**; submitted question IDs are scoped to the logged-in user and roadmap.
- Tracks streaks, check-ins, mock-test schedules, revision, monthly reviews, and CSV/calendar exports.
- Uses free public resources (Wikipedia, Crossref, GitHub) when external fetching is enabled.
- **Rewards progress with titles and badges.** A live momentum panel on the dashboard and every roadmap derives a title from real completion, on-time work, streak, and check-in consistency, plus an earned-badge shelf and a progress bar toward the next badge. Momentum rises with finished work and falls when tasks go overdue or the plan goes quiet, so the same panel encourages recovery after a slip.

## Titles, badges, and login motivation

The momentum engine is computed server-side from persisted tasks and check-ins — nothing is client-assigned.

| Momentum score | Title | Tone |
| --- | --- | --- |
| All tasks complete | Roadmap Finisher | positive |
| ≥5 overdue, or ≥2 overdue with a stale plan, or 10+ days with zero progress | Momentum at Risk | danger |
| Any overdue task, no check-in for 7+ days, or 7+ days with zero progress | Catching Up | warning |
| Score ≥ 75 | Momentum Architect | positive |
| Score ≥ 55 | Momentum Builder | positive |
| Score ≥ 35 | Steady Climber | positive |
| At least one task done | Momentum Starter | positive |
| No tasks done yet | Fresh Start | positive |
| No roadmap yet | Starting Line | positive |

Score = 55% completion + 25% on-time completion + 20% consistency (streak and recent check-ins), minus 6 per overdue task (capped at −30).

Earned badges: First Step, Five Wins, Ten Down, Streak Starter, Project Shipper, Halfway Hero, Consistency Keeper, Portfolio Proof, Roadmap Finisher. Recovery badges appear only when the plan drifts: Delay Alert, Overdue Stack, Re-Entry Needed, Still at the Start. Each badge carries its own tone and next-step hint, and the panel always shows the nearest unearned badge with progress toward it. A motivational message is rendered on the dashboard at login, including for accounts with no roadmap yet.

## Zero-cost PYQ pipeline

The app downloads open-source PYQ archives at runtime and caches them in the `question` table:

- Prelims: `S-bandawala/upsc-quiz-app` open JSON archive. 2016 and 2024 are imported as **archive** practice because their keys are not officially verified; all other years are served as **verified**.
- Mains: `amanbh2/UPSC-Star` open archive, filtered by paper, year, marks, and word limit.
- Every cached question is tagged with the UPSC GS taxonomy (subject + topic) and questions that depend on a missing figure/map/table are dropped. Selection prefers verified questions, exact weak-topic matches, and year spreading for mocks.
- A **bundled seed** (`pyq/seed/upsc_bank.json.gz`, ~175 KB) loads a validated bank on first boot, so UPSC practice works even before the first network sync.
- Downloads use `ETag`/`Last-Modified` conditional requests and a SHA-256 content hash; a `304 Not Modified` keeps the cache untouched. Sync state lives in `pyq_sync_state`, refreshes weekly (`PYQ_REFRESH_DAYS`), and fails independently per source.
- When a cache exists, refreshes run in the background; the bundled seed makes the first test instant. Admins listed in `ADMIN_EMAILS` can force a sync from the practice/materials page.

For papers that are missing from public archives, `scripts/import_official_papers.py` imports official PDFs deterministically. Official UPSC PDFs are usually scanned, so the importer asks for OCR text (`--text-file`) and the official key (`--key-file`) for prelims; mains papers need no key. No LLM or paid service is used.

```bash
# Mains paper that has a text layer
python scripts/import_official_papers.py --stage mains --year 2024 --paper GS-I \
  --pdf instance/official/mains2024_gs1.pdf

# Scanned prelims paper: OCR first (free), then supply text + official key
python scripts/import_official_papers.py --stage prelims --year 2025 \
  --text-file instance/official/prelims2025_ocr.txt \
  --key-file instance/official/prelims2025_key.txt --set A

# Verify parsing without writing anything
python scripts/import_official_papers.py --stage mains --year 2024 --paper GS-I \
  --pdf instance/official/mains2024_gs1.pdf --dry-run --json-out parsed.json
```

Prelims 2025 is intentionally absent from the bundled seed: the public archive has the questions but no answer keys, and the importer refuses to guess. Run the importer with the official key when it is available locally.

No LLM, paid API, or subscription is used anywhere in the app. The platform is designed to run entirely on free and open sources. Local OCR via Tesseract is optional and only runs when you upload an image syllabus.

## Tech stack

- Flask 3 + SQLAlchemy 2 + Flask-Migrate
- SQLite for local development, Supabase/Postgres for production
- Gunicorn on Render's free web-service tier
- Server-rendered Jinja templates, no frontend build step

## Local setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Create `.env`:
   ```env
   APP_ENV=development
   SECRET_KEY=replace-me
   DATABASE_URL=sqlite:///db.sqlite3
   AUTO_CREATE_SCHEMA=true
   ENABLE_EXTERNAL_RESOURCES=true
   PYQ_SYNC_ENABLED=true
   SESSION_COOKIE_SECURE=false
   UPLOAD_FOLDER=uploads
   ```
   `AUTO_CREATE_SCHEMA=true` is for local SQLite only. Production should run `supabase/setup.sql` (or Flask-Migrate) and keep it `false`.
3. Run:
   ```bash
   python app.py
   ```
4. Open `http://127.0.0.1:5000`. The bundled PYQ seed loads on first boot, so UPSC practice works immediately; a background refresh checks the public archives when the cache is stale.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Set `production` to require a real `SECRET_KEY` and default to secure cookies |
| `SECRET_KEY` | dev placeholder | Session signing key; mandatory in production |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Postgres/Supabase in production |
| `AUTO_CREATE_SCHEMA` | `false` | Local convenience only |
| `PYQ_SYNC_ENABLED` | `true` | Enable the free PYQ archive sync |
| `PYQ_REFRESH_DAYS` | `7` | Cache freshness window |
| `PYQ_REQUEST_TIMEOUT_SECONDS` | `20` | Archive download timeout |
| `PYQ_SEED_ENABLED` | `true` | Load the bundled validated bank on first boot |
| `PYQ_SEED_PATH` | `pyq/seed/upsc_bank.json.gz` | Seed fixture location |
| `ADMIN_EMAILS` | empty | Comma-separated accounts allowed to force a PYQ sync |
| `ENABLE_EXTERNAL_RESOURCES` | `true` | Wikipedia/Crossref/GitHub lookups |
| `RESOURCE_MAX_ITEMS` | `6` | Free resources fetched per topic |
| `RESOURCE_VERIFY_URLS` | `true` | HEAD-check resource links and hide dead ones |
| `AUTO_FETCH_RESOURCES_ON_CREATE` | `false` | Background resource fetch at roadmap creation (career plans always fetch when external resources are enabled) |
| `SESSION_COOKIE_SECURE` | follows `APP_ENV` | Must be `true` behind HTTPS |
| `RATELIMIT_ENABLED` | `true` | In-process rate limits for auth and test generation |
| `ORIGIN_CHECK_ENABLED` | `true` | Reject cross-site state-changing requests |
| `MAX_CONTENT_LENGTH_MB` | `20` | Upload size cap |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | empty | Optional evidence storage |

## Production deployment (free tier)

1. Create a Supabase project and copy the Postgres connection string.
2. Run [`supabase/setup.sql`](supabase/setup.sql) in the Supabase SQL editor. It is idempotent and includes upgrades for older databases.
3. Push this repository to GitHub.
4. In Render, create a **Web Service**, connect the repo, and use:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn --workers 1 --threads 8 --timeout 120 --access-logfile - app:app`
   - Health check: `/healthz`
5. Set environment variables (or deploy the included [`render.yaml`](render.yaml)):
   - `APP_ENV=production`
   - `SECRET_KEY` (Render can generate it)
   - `DATABASE_URL`
   - `SESSION_COOKIE_SECURE=true`
   - `PYQ_SYNC_ENABLED=true`
   - `PYQ_SEED_ENABLED=true`
   - `ADMIN_EMAILS=you@example.com` (optional; enables the force-sync button)
   - `AUTO_CREATE_SCHEMA=false`
6. Deploy and open `/healthz`; it should return `{"status":"ok","database":"up"}`.

Single-worker Gunicorn is intentional on the free tier: the in-process PYQ sync lock and rate limiter stay consistent, and threads handle concurrent requests.

## Security notes

- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
- State-changing requests are rejected when `Origin`/`Referer` or `Sec-Fetch-Site` indicates another site.
- Login/registration, roadmap creation, quiz generation, and quiz submission are rate limited.
- Security headers include CSP, `X-Frame-Options: DENY`, `nosniff`, a restrictive referrer policy, and HSTS on HTTPS.
- Evidence downloads require ownership of the referenced task; Supabase paths must belong to the current user.
- Test scoring is derived from persisted questions, never from client-submitted totals or answers.
- Run `python -m unittest tests.test_smoke` before deploying.

## Folder structure

```
Dreams-into-Reality/
  app.py               # app factory wiring, health check, schema bootstrap
  security.py          # origin checks, rate limits, security headers
  config.py            # environment configuration
  auth/                # register/login/logout
  dashboard/           # planning, PYQ practice, analytics, exports
  pyq/                 # zero-cost ingestion, validation, selection
  models/              # SQLAlchemy models
  templates/ static/   # server-rendered UI
  supabase/setup.sql   # idempotent production schema
  tests/               # smoke and behaviour tests
```

## Attribution and disclaimer

PYQs are compiled from public open-source archives and cached locally; they are not resold or claimed as original. The official UPSC question papers and answer keys remain the final authority. Mains frameworks and interview prompts are original preparation scaffolds, not official answers or transcripts. Always verify facts, figures, and answer keys against official sources.

---

Maintained by **Anish Kumar**.
