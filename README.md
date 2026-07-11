# Concall Intelligence Platform

<img width="1919" height="1037" alt="Screenshot 2026-07-12 013140" src="https://github.com/user-attachments/assets/cd1f699e-78ba-4f3f-b927-51f38a2b5f76" />
<img width="1919" height="1037" alt="Screenshot 2026-07-12 013152" src="https://github.com/user-attachments/assets/0d8088dd-785f-4d39-989d-f3441498cabf" />
<img width="1916" height="1031" alt="Screenshot 2026-07-12 013214" src="https://github.com/user-attachments/assets/cbdc4e37-4b1a-4862-8b64-8b0d5b767fb4" />
<img width="1919" height="1026" alt="Screenshot 2026-07-12 013225" src="https://github.com/user-attachments/assets/f40c4c9d-a003-4c46-ac77-df179fa81079" />
<img width="1916" height="1026" alt="Screenshot 2026-07-12 013551" src="https://github.com/user-attachments/assets/d2d20bce-0533-4df8-9b44-65a8a7214a3b" />



Upload quarterly earnings-call (concall) transcripts for a portfolio of companies.
The system extracts text, pulls structured metrics + management guidance, tracks
**whether past guidance was actually fulfilled in later quarters (with the chain)**,
flags red flags, scores each company against the **Business Analysis Template**
(10 sections, 0-10 each -> /100), and ranks stocks on leaderboards.

This is a **prototype scaffold**: the pipeline runs end-to-end in-process with
deterministic stub implementations for the heavy parts (OCR + LLM), so you can run
it today and swap in real providers (Azure Document Intelligence, Azure OpenAI)
without changing the architecture.

> Decision-support only. Not financial advice. Every extracted fact carries a
> verbatim source quote + transcript id for auditability.

## Architecture (event-driven, per-stage workers)

```
Upload PDF -> Ingestion -> Extraction -> LLM Analysis -> Guidance Reconciler -> Scoring -> Dashboard
             (blob+hash)  (DocIntel/OCR) (JSON schema)   (promise vs actual)   (10 sect)  (leaderboards)
```

Each stage is idempotent on `company_id + fiscal_year + quarter + content_hash`.
In this scaffold the stages are chained by `app/workers/pipeline.py`; in production
each becomes a queue consumer (Kafka / Azure Service Bus / SQS).

## The 10-section scoring model (from Analysis_Template.pdf)

1 Business simplicity · 2 Revenue growth · 3 Profit growth · 4 Return on capital ·
5 Debt safety · 6 Moat · 7 Management quality · 8 Industry opportunity ·
9 Valuation · 10 Red flags & governance. TOTAL /100 -> decision band
(85+ Exceptional, 75-85 High, 65-75 Good, 50-65 Average, <50 Avoid).

## Guidance -> Outcome chain (the differentiator)

- Every forward-looking statement in a call -> a `guidance` row (target, period, verbatim quote).
- When a later quarter arrives, open guidance whose target_period has passed is
  resolved into `guidance_outcome` (MET / MISSED / PARTIAL / IN_PROGRESS / DROPPED).
- `guidance_reliability_score = MET / (MET + MISSED + PARTIAL)` feeds Section 7.

## Getting real insights (three ways to run the analysis)

The pipeline is provider-agnostic (`LLM_PROVIDER` in `.env`):

1. **`agent`** — no external API key. The agent (Copilot) reads the extracted
   transcript in-session, writes `data/analyses/{TICKER}_{FY}Q{Q}.json`, and the
   pipeline consumes it. Real, grounded insights with verbatim quotes.
   ```powershell
   python -m app.cli extract RAIN "Rain Industries Limited" 2026 1 "C:\path\to\transcript.pdf"
   #  (agent reads data\RAIN_2026Q1.txt and writes data\analyses\RAIN_2026Q1.json)
   python -m app.cli load-analysis RAIN 2026 1
   ```
2. **`openai`** — fully automatic. Put your key in `.env`:
   ```
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-2024-08-06
   ```
   Then uploading a PDF in the UI returns insights instantly (Structured Outputs).
3. **`azure_openai`** — same, using an Azure deployment.

## Web UI

```powershell
uvicorn app.main:app --port 8010
# open http://localhost:8010
```
Tabs: **Dashboard** (leaderboards), **Company Insights** (score gauge, 10-section
bars, red flags, future guidance, guidance→outcome chains), **Upload Transcript**.

## Quick start (demo data)

```powershell
# 1. Create venv + install deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Start Postgres (with pgvector). Easiest via docker:
docker compose up -d db

# 3. Point the app at the DB and create tables + seed
copy .env.example .env
python -m app.cli initdb

# 4. Run the API
uvicorn app.main:app --reload

# 5. Try it (in another shell)
python -m app.cli demo   # ingests 3 synthetic quarters for a demo company
#   open http://localhost:8000/docs
```

Without Docker you can run against **SQLite** by setting
`DATABASE_URL=sqlite:///./concall.db` in `.env` (vector search is disabled in that mode).

## Layout

```
app/
  config.py          settings (env-driven)
  db.py              engine/session
  models.py          SQLAlchemy ORM (companies, transcripts, metrics, guidance, scores...)
  schemas.py         Pydantic I/O + the 10-section template schema
  main.py            FastAPI app
  cli.py             initdb / demo helpers
  api/               routes: companies, transcripts, dashboard
  services/          ingestion, extraction, analysis, guidance, scoring
  llm/               LLM client abstraction + prompts (mapped to template)
  workers/           pipeline orchestration (in-proc; queue-ready)
sql/schema.sql       raw DDL (reference; ORM creates tables)
tests/               unit tests for guidance reconciliation + scoring
```

## Swapping stubs for real providers

- `app/services/extraction.py::extract_text` -> Azure Document Intelligence / AWS Textract, Tesseract OCR fallback.
- `app/llm/client.py::LLMClient` -> Azure OpenAI / OpenAI with JSON-schema function calling.
  Set `LLM_PROVIDER=azure_openai` and the related env vars; the stub is used otherwise.
