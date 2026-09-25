# SmartPrep Python

SmartPrep Python is the backend service for **SmartPrep**, a criminology review and examination platform. It provides the API, persistence, document-processing, background-analysis, real-time notification, and LLM-assisted analytics used by the SmartPrep Modern Windows desktop client.

> **Project context:** The complete SmartPrep system was developed in under two months. This backend combines FastAPI, MySQL, Redis/Celery, WebSockets, PDF processing, and Ollama-backed analysis.

## Key features

- **Exam and source APIs** — manages categories, topic slots, PDF sources, exam rules, generation, assignments, and submissions.
- **PDF questionnaire extraction** — processes uploaded questionnaire files into structured questions used by the exam workflow.
- **Analytics and forensics** — provides leaderboards, trends, attempt comparisons, question distributions, and deeper item/attempt analysis.
- **Background analysis** — Celery and Redis run scheduled analytical jobs outside the request cycle.
- **LLM-assisted insights** — Ollama-backed workflows generate structured performance analysis and recommendations.
- **Real-time updates** — WebSocket endpoints support live client notifications and synchronization.

## Architecture

```text
SmartPrep Modern (WPF desktop client)
                │
                │ REST / WebSocket
                ▼
┌─────────────────────────────────────┐
│ FastAPI                             │
│                                     │
│ /auth       authentication/users    │
│ /slots      topics + PDF sources    │
│ /exam       exam lifecycle          │
│ /analytics  reporting/forensics     │
│ /ws         real-time updates       │
│ /sr_libs    API schema export       │
└──────────────┬──────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
   MySQL DB        Redis (6379)
                       │
                       ▼
                 Celery workers
                 + Celery Beat
                       │
                       ▼
                 Ollama / LLM
                 analysis jobs
```

## Processing workflow

Questionnaire PDFs can be uploaded into topic slots and extracted into structured questions for exam generation. Celery workers handle scheduled exam, attempt, and item analysis, with Redis used for task coordination and locking. LLM analysis returns structured results consumed by the desktop analytics interface.

Runtime source files are stored under `uploads/questionnaires/` and `uploads/materials/`.

## Questionnaire document format

Questionnaires, examination materials, and other confidential source documents are runtime/local data and are intentionally **not included in this repository**.

Questionnaire PDFs cannot use an arbitrary layout. To keep uploads fast on the hardware available when SmartPrep was developed, questionnaire ingestion uses a lightweight **pattern/regex-based parser** instead of sending the entire PDF through the local LLM. The PDF should contain text in this structure:

```text
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

Questions must start with a number followed by `.` or `)`, choices must use `A`–`D` followed by `.` or `)`, and each item needs at least two choices plus an `Answer:` line. The answer may be the choice letter or the matching choice text. PDFs must also contain extractable text; scanned image-only PDFs require OCR first.

If an existing questionnaire uses another layout, you can ask ChatGPT, Claude, or another capable model to reformat it before uploading:

> Reformat this questionnaire without changing its questions, choices, or correct answers. Output each item as: a numbered question (`1.`), choices labeled `A.` through `D.`, and a final `Answer: X` line containing the correct choice letter. Keep each question, choice, and answer on its own line. Do not add explanations, remove questions, or invent answers.

This was a deliberate performance tradeoff: deterministic parsing keeps questionnaire uploads immediate and reserves the local Ollama model for the analytical workflows where LLM reasoning is more useful.

## Technology stack

| Area | Technology |
| --- | --- |
| API | FastAPI, Uvicorn |
| Validation | Pydantic |
| Database | MySQL (`mysql-connector-python`) |
| Background jobs | Celery |
| Broker / task backend / locks | Redis |
| Real-time communication | WebSockets |
| PDF processing | PyPDF2 |
| AI analysis | Ollama client |
| Authentication/security | bcrypt, PyJWT |
| Configuration | python-dotenv |

The repository's dependency file contains additional experimental/data/AI packages. The table above focuses on technologies directly represented in the current application flow.

## Project structure

```text
SmartPrepPython/
├── api/
│   ├── analytics/       # Analytics, trends, leaderboards, forensics
│   ├── auth/            # Authentication and user management
│   ├── exam/            # Exam rules, generation, sessions, submissions
│   ├── slots/           # Categories, source slots, PDF uploads
│   ├── sr_libs/         # API schema export
│   └── websocket/       # WebSocket/update endpoints
├── utils/
│   ├── connection.py    # WebSocket connection manager
│   ├── db.py            # Database access wrapper
│   ├── email.py         # Password-recovery email
│   ├── extractor.py     # Questionnaire extraction
│   ├── ollama.py        # LLM analysis functions
│   └── password_helper.py
├── main.py              # FastAPI application composition
├── tasks.py             # Celery workers and scheduled analysis
└── requirements.txt
```

## Local setup

### 1. Requirements

- Python 3.11+ recommended
- Redis on `localhost:6379`
- MySQL-compatible database
- Ollama-compatible server/model for AI analysis

> **Database note:** the current source is written specifically for MySQL, not PostgreSQL. It uses `mysql-connector-python` and several MySQL-specific SQL constructs (`JSON_TABLE`, `GROUP_CONCAT`, and `ON DUPLICATE KEY UPDATE`). A PostgreSQL instance on port 5432 cannot be substituted by changing `.env` alone; the database adapter and affected queries would need to be migrated.

### 2. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in the local values:

```powershell
Copy-Item .env.example .env
```

The included local `.env` template assumes Redis is available through Docker Desktop on port `6379`.

### 4. Start the API

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

FastAPI documentation will then be available at `/docs` on the local API server.

### 5. Start the Celery worker

In another PowerShell terminal with the virtual environment active:

```powershell
celery -A tasks.app worker --loglevel=info --pool=solo
```

`--pool=solo` is useful for local Celery development on Windows.

### 6. Start Celery Beat

In a third terminal:

```powershell
celery -A tasks.app beat --loglevel=info
```

### 7. Start SmartPrep Modern

Run the companion WPF client and point `SMARTPREP_API_BASE_URL` to `http://127.0.0.1:8000/`.

### 8. Activate the first administrator

The first Admin account should be **registered through SmartPrep Modern**, not inserted manually into MySQL. Registration creates the account with a `locked` status.

After registration, connect to MySQL with any database-management client and change that account's `users.status` from `locked` to `active`.

With the provided Docker setup, the database is exposed at:

```text
Host:     127.0.0.1
Port:     3307
Database: smartprep
User:     smartprep
Password: <your configured DB password>
```

You can edit the `status` cell directly in the `users` table, or run:

```sql
UPDATE users
SET status = 'active'
WHERE username = 'YOUR_ADMIN_USERNAME';
```

After activation, return to SmartPrep Modern and log in with the administrator account.


## Docker restoration

For the restored local environment, the backend can be run with Docker Compose while SmartPrep Modern remains a native Windows application.

The Docker setup runs:

- `smartprep-mysql`
- `smartprep-api`
- `smartprep-celery-worker`
- `smartprep-celery-beat`

It can reuse Redis already exposed through Docker Desktop/Windows on port `6379`.

From the folder containing `docker-compose.yml`:

```powershell
docker compose up -d --build
```

The API is then available at:

```text
http://localhost:8000
http://localhost:8000/docs
```

MySQL is exposed to the host on port `3307`, while the container itself uses the standard MySQL port `3306`.

The initialization SQL under `docker/mysql/init/` runs automatically only when the MySQL data volume is created for the first time. To intentionally rebuild the local database from the initialization SQL:

```powershell
docker compose down -v
docker compose up -d --build
```

> The restoration schema was reconstructed from the database relationships exercised by the preserved Python source. It should not be presented as the original lost schema; exact historical constraints, defaults, indexes, and field lengths may differ.

## Environment variables

| Variable | Purpose | Local example |
| --- | --- | --- |
| `DB_HOST` | MySQL host | `127.0.0.1` |
| `DB_PORT` | Database port (reserved for local config) | `3306` |
| `DB_USER` | Database user | `root` |
| `DB_PASSWORD` | Database password | local value |
| `DB_NAME` | SmartPrep database | `smartprep` |
| `CELERY_BROKER_URL` | Redis/Celery connection | `redis://localhost:6379/1` |
| `OLLAMA_HOST` | Ollama-compatible server | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model used for analysis | your installed model |
| `EMAIL_SENDER` | SMTP sender for recovery mail | optional |
| `EMAIL_PASSWORD` | SMTP/app password | optional |
| `SMTP_SERVER` | SMTP host | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |

## Desktop client

The companion Windows client is available at:

https://github.com/SaintRelion/SmartPrepModern

## Security

Secrets should never be committed to source control. SMTP credentials and external service configuration are loaded from environment variables in the local-ready version of this project.

If a credential was previously committed to Git history, rotate/revoke it before making the repository public; removing it from the latest file does not remove it from previous commits.

## Engineering notes

This repository reflects a system delivered under a short development window and is preserved as an example of an end-to-end client/server implementation. Newer projects may use different abstractions or architecture as the author's engineering practices have continued to evolve.

## Author

**June Aurelius Jacinto**  
Full-Stack Software Developer

GitHub: https://github.com/SaintRelion
