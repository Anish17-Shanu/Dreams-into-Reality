# Dreams into Reality

Dreams into Reality helps individual learners turn a **syllabus or career goal** into a structured roadmap with tasks, timelines, and curated web resources. Upload your syllabus (PDF/TXT), choose a timeline, and track every step toward your goal.

## Features
- Syllabus or career roadmaps with adaptive timelines (PDF/TXT/DOCX/images)
- Dynamic career skills pulled from public career taxonomies (ESCO) when you type a career goal
- Smart task chunking with difficulty + estimated hours
- Progress tracking with streaks, check-ins, and forecasted finish dates
- Preview/edit topics before generating a roadmap
- Resource discovery and ranking from free public APIs
- Resource feedback (rating/flagging) and refresh controls
- Evidence uploads, notes, and exports (CSV + calendar)
- Secure user accounts with saved progress (Supabase Postgres)
- Ready for deployment on Render

## Tech Stack
- Flask + SQLAlchemy
- Supabase (Postgres)
- Render deployment
- External resource APIs: Wikipedia REST API, Crossref, GitHub Search

## Local Setup
1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Create a `.env` file:
   ```env
   SECRET_KEY=replace-me
   DATABASE_URL=postgresql://user:pass@host:5432/dbname
   ENABLE_EXTERNAL_RESOURCES=true
   WIKIPEDIA_USER_AGENT=DreamsIntoReality/1.0 (contact@youremail.com)
   CROSSREF_MAILTO=contact@youremail.com
   GITHUB_TOKEN=optional_github_token
   RESOURCE_REFRESH_DAYS=7
   REQUEST_TIMEOUT_SECONDS=8
   OPENAI_API_KEY=your_openai_key
   OPENAI_MODEL=gpt-5
   AI_TOPIC_EXTRACTION_ENABLED=false
   HF_API_KEY=your_hf_key
   HF_MODEL=google/flan-t5-large
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=service_role_key
   SUPABASE_STORAGE_BUCKET=evidence
   SIGNED_URL_EXPIRES_SECONDS=600
   AUTO_FETCH_RESOURCES_ON_CREATE=true
   DEFAULT_TIMEZONE=Asia/Kolkata
   ```
3. Run the app:
   ```bash
   python app.py
   ```

## Supabase Setup
1. Create a new Supabase project.
2. In Supabase, go to **Project Settings > Database > Connection string**.
3. Use the **Connection string** as your `DATABASE_URL`.
4. (Optional) Use the **Connection Pooler** for production if you expect heavy traffic.
5. Run the SQL setup script from `supabase/setup.sql` in the Supabase SQL editor.

## Render Deployment
1. Push this repo to GitHub.
2. Create a new **Web Service** on Render.
3. Connect your GitHub repo and choose the branch.
4. Set build and start commands:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app`
5. Add the following environment variables in Render:
   - `DATABASE_URL` (from Supabase)
   - `SECRET_KEY`
   - `ENABLE_EXTERNAL_RESOURCES` (true/false)
   - `WIKIPEDIA_USER_AGENT` (recommended)
   - `CROSSREF_MAILTO` (recommended)
   - `GITHUB_TOKEN` (optional, increases GitHub API limits)
6. Deploy.

## Free API Notes
- **Wikipedia REST API**: Used for topic summaries. Requires a clear `User-Agent`.
- **Crossref API**: Used for academic references. Provide a `mailto` in requests.
- **GitHub Search API**: Finds repos for hands-on learning. Add a token to avoid low rate limits.
- **Optional OCR**: Image-based syllabus upload uses `pytesseract`. Install the Tesseract binary if you want OCR enabled.
- **Refresh cooldown**: Resources refresh every `RESOURCE_REFRESH_DAYS` to avoid rate limits.
- **AI extraction**: Turn on `AI_TOPIC_EXTRACTION_ENABLED` or check the UI box to use OpenAI's Responses API for messy syllabi.
- **Free AI alternative**: Provide `HF_API_KEY` to use Hugging Face Inference for topic extraction if OpenAI isn't configured.
- **No-API fallback**: A stronger rule-based parser handles bullets, units, and numbered sections when no AI is configured.
- **Render tip**: `AUTO_FETCH_RESOURCES_ON_CREATE=true` triggers background fetching so creation stays fast.
- **Career templates**: We query ESCO for occupation skills when you choose `career` and don’t show a fixed list.

## Roadmap Creation
- **Syllabus**: Paste topics or upload a PDF/TXT. Topics become tasks.
- **Career**: Use a built-in career template (e.g., `frontend developer`, `data analyst`) or paste your own outline.
- **Adaptive schedule**: Leave timeline weeks blank to auto-calculate based on study hours.

## Folder Structure
```
Dreams-into-Reality/
  app.py
  auth/
  dashboard/
  models/
  templates/
  static/
```

## Deployment Checklist
- Supabase database created
- `DATABASE_URL` set in Render
- `SECRET_KEY` set in Render
- Supabase Storage bucket created (default: `evidence`)
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` set in Render
- Run migrations when updating models:
  ```bash
  flask db init
  flask db migrate -m "init"
  flask db upgrade
  ```

---

If you want to expand career templates or add AI-driven roadmaps later, this codebase is ready for it.
