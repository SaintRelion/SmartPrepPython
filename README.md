# SmartPrep Python

SmartPrep Python is the backend for **SmartPrep**, a review and
examination platform paired with the SmartPrep Modern Windows desktop
client. It provides the API, document processing, exam workflows,
analytics, background jobs, real-time updates, and Ollama-assisted
analysis used by the desktop application.

> SmartPrep was developed as an end-to-end system in under two months.

## Key features

-   **Exam and source APIs** --- categories, topic slots, source
    documents, exam rules, generation, assignments, and submissions.
-   **PDF questionnaire extraction** --- converts structured
    questionnaire PDFs into questions used by the exam workflow.
-   **Analytics and forensics** --- leaderboards, trends, attempt
    comparisons, distributions, and item-level analysis.
-   **Background analysis** --- Celery workers and Celery Beat handle
    scheduled analytical workloads.
-   **LLM-assisted insights** --- Ollama-backed workflows generate
    structured analysis and recommendations.
-   **Real-time updates** --- WebSocket endpoints support live
    desktop-client updates.
-   **Containerized backend stack** --- Docker Compose runs the API,
    MySQL, Redis, Celery worker, and Celery Beat.

## Stack

-   FastAPI + Uvicorn
-   MySQL
-   Redis
-   Celery + Celery Beat
-   WebSockets
-   PyPDF2
-   Ollama
-   Astral `uv` for Python dependency and environment management
-   Docker / Docker Compose

## Run with Docker

For the backend, Docker Compose is the simplest setup:

``` powershell
docker compose up -d --build
```

The Compose stack runs:

``` text
smartprep-api
smartprep-mysql
smartprep-redis
smartprep-celery-worker
smartprep-celery-beat
```

The API is available at:

``` text
http://localhost:8000
http://localhost:8000/docs
```

MySQL is exposed to the host on port `3307` by default. Redis is
internal to the Compose network and does not need to be exposed to the
host.

The SmartPrep Modern WPF client remains a native Windows application and
connects to the backend API separately.

Useful commands:

``` powershell
docker compose ps
docker compose logs -f --tail=100 api
docker compose logs -f --tail=100 celery-worker
docker compose down
```

The initialization SQL under `docker/mysql/init/` runs when the MySQL
data volume is created for the first time. To intentionally rebuild the
local database from that initialization SQL:

``` powershell
docker compose down -v
docker compose up -d --build
```

> The restoration schema was reconstructed from database relationships
> exercised by the preserved Python source. Exact historical
> constraints, defaults, indexes, and field lengths may differ.

### Dependency management

The Python project uses **Astral uv** with `pyproject.toml` and
`uv.lock`. Docker installs the locked environment with `uv sync`,
keeping dependency resolution consistent between development and the
image.

Application source is kept under `src/`, while project/deployment files
such as `pyproject.toml`, `uv.lock`, `.env`, Dockerfile, and Compose
remain at the repository root.

## How SmartPrep processes questionnaires

Questionnaire PDFs are uploaded into topic slots and parsed into
structured questions for exam generation. The preserved implementation
uses a deterministic text format instead of sending every uploaded
questionnaire through the LLM.

> **Modernization note:** SmartPrep was built when capable language
> models for this kind of document workflow required substantially more
> expensive infrastructure. Questionnaire extraction therefore used
> deterministic parsing while the available LLM capacity was reserved
> for higher-value analytical tasks. I plan to modernize this pipeline when I have some available
> development time, replacing the rigid parsing requirement with
> LLM-assisted document extraction. Today, capable lower-cost models make
> this much more practical, allowing SmartPrep to accept less structured
> questionnaire formats without requiring the kind of dedicated GPU
> setup used by the original system.

The current preserved parser expects a compatible questionnaire format
such as:

``` text
1. Question text
A. First choice
B. Second choice
C. Third choice
D. Fourth choice
Answer: A

2. Next question
A. First choice
B. Second choice
C. Third choice
D. Fourth choice
Answer: C
```

Questions start with a number followed by `.` or `)`. Choices use
`A`--`D` followed by `.` or `)`, and each item needs at least two
choices plus an `Answer:` line. PDFs must contain extractable text;
scanned image-only PDFs require OCR first.

Runtime questionnaire and study-material files are intentionally not
included in the repository.

## Background analysis

Redis serves as the Celery broker/backend and also supports distributed
locking for scheduled analysis. Celery workers handle examination,
attempt, and question-level analysis outside the API request cycle,
while Ollama is used for the analytical workflows where LLM reasoning is
useful.

## First administrator

Register the first administrator through SmartPrep Modern. New
registration creates the account in a locked state.

After registration, connect to MySQL and change the account's
`users.status` from `locked` to `active`:

``` sql
UPDATE users
SET status = 'active'
WHERE username = 'YOUR_ADMIN_USERNAME';
```

Then return to SmartPrep Modern and sign in.

## Local setup without Docker

This section is only needed if you want to run the backend services
directly on your machine.

### 1. Install uv

On Windows:

``` powershell
winget install --id=astral-sh.uv -e
```

Verify and restore the project environment:

``` powershell
uv --version
uv sync
```

### 2. Local services

For a fully local run, provide:

-   MySQL
-   Redis on `localhost:6379`
-   an Ollama-compatible server/model for AI analysis

Configure `.env` with your local database, Ollama, and optional email
settings. Redis/Celery connection settings do not need to be stored in
`.env`; the application defaults to local Redis when running outside
Docker, while Compose supplies the internal Redis hostname in
containers.

The current database layer is MySQL-specific and uses MySQL-specific SQL
constructs, so PostgreSQL cannot be substituted by changing environment
variables alone.

### 3. Start the API

The application source lives under `src/`. From the repository root:

``` powershell
uv run uvicorn --app-dir src main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Start Celery

In another terminal:

``` powershell
uv run celery --workdir src -A tasks.app worker --loglevel=info --pool=solo
```

For local Windows development, `--pool=solo` avoids multiprocessing
issues commonly encountered by Celery on Windows.

Start Celery Beat in another terminal:

``` powershell
uv run celery --workdir src -A tasks.app beat --loglevel=info
```

### 5. Start the desktop client

Run SmartPrep Modern and point its API base URL to:

``` text
http://127.0.0.1:8000/
```

## Security

Secrets and service credentials are intentionally not committed. If a
credential was previously committed to Git history, it should be
revoked/rotated and removed from history rather than only deleting it
from the latest file.

## Author

**June Aurelius Jacinto**\
Full-Stack Software Developer

GitHub: https://github.com/SaintRelion
