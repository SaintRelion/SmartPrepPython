SmartPrep Python

SmartPrep Python is the backend service for SmartPrep, a criminology review and examination platform. It provides the API, persistence, document-processing, background-analysis, real-time notification, and LLM-assisted analytics used by the SmartPrep Modern Windows desktop client.

Project context: The complete SmartPrep system was developed under a compressed delivery timeline of less than two months. The backend combines a FastAPI application with a relational database, Redis, Celery workers, scheduled analysis jobs, WebSockets, PDF ingestion, and Ollama-backed analysis workflows.

System responsibilities

The backend exposes domain-specific API modules for:

User registration, login, account management, status control, and password recovery

Categories and topic/source slots

PDF questionnaire and study-material uploads

Questionnaire extraction into structured questions

Exam rules and exam generation

Exam listing, retrieval, reviewee assignment/status, and answer submission

Global and per-subject leaderboards

Exam analytics and comparative performance trends

Topic growth trends

Basic attempt comparisons and deeper attempt forensics

Per-question distribution analysis

AI-generated attempt, item, and cohort-level analysis

WebSocket connections and update notifications

API schema export for the companion client

Architecture

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

Background analysis

tasks.py defines scheduled Celery workflows for asynchronous analysis. Redis is used as both the Celery broker/backend and as a distributed lock so the same analysis category is not processed concurrently by multiple scheduled runs.

The scheduled workflows include:

Examination item-distribution analysis

Examination-attempt analysis

Individual question/item analysis

The LLM layer produces structured JSON used by the analytics UI for instructor-facing diagnostics, reviewee feedback, recommendations, and question-level explanations.

PDF/source workflow

The /slots/upload_source_file endpoint accepts questionnaire or study-material PDFs. Uploaded files are separated into questionnaire/material storage, and questionnaire files are passed through the extraction pipeline to create structured questionnaire items associated with a topic slot.

Runtime uploads are stored under:

uploads/
├── questionnaires/
└── materials/

These directories can be populated with test documents after the application is running.

Technology stack

Area

Technology

API

FastAPI, Uvicorn

Validation

Pydantic

Database

MySQL (mysql-connector-python)

Background jobs

Celery

Broker / task backend / locks

Redis

Real-time communication

WebSockets

PDF processing

PyPDF2

AI analysis

Ollama client

Authentication/security

bcrypt, PyJWT

Configuration

python-dotenv

The repository's dependency file contains additional experimental/data/AI packages. The table above focuses on technologies directly represented in the current application flow.

Project structure

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

Local setup

1. Requirements

Python 3.11+ recommended

Redis on localhost:6379

MySQL-compatible database

Ollama-compatible server/model for AI analysis

Database note: the current source is written specifically for MySQL, not PostgreSQL. It uses mysql-connector-python and several MySQL-specific SQL constructs (JSON_TABLE, GROUP_CONCAT, and ON DUPLICATE KEY UPDATE). A PostgreSQL instance on port 5432 cannot be substituted by changing .env alone; the database adapter and affected queries would need to be migrated.

2. Create a virtual environment

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

3. Configure environment variables

Copy .env.example to .env and fill in the local values:

Copy-Item .env.example .env

The included local .env template assumes Redis is available through Docker Desktop on port 6379.

4. Start the API

uvicorn main:app --reload --host 127.0.0.1 --port 8000

FastAPI documentation will then be available at /docs on the local API server.

5. Start the Celery worker

In another PowerShell terminal with the virtual environment active:

celery -A tasks.app worker --loglevel=info --pool=solo

--pool=solo is useful for local Celery development on Windows.

6. Start Celery Beat

In a third terminal:

celery -A tasks.app beat --loglevel=info

7. Start SmartPrep Modern

Run the companion WPF client and point SMARTPREP_API_BASE_URL to http://127.0.0.1:8000/.

8. Activate the first administrator

The first Admin account should be registered through SmartPrep Modern, not inserted manually into MySQL. Registration creates the account with a locked status.

After registration, connect to MySQL with any database-management client and change that account's users.status from locked to active.

With the provided Docker setup, the database is exposed at:

Host:     127.0.0.1
Port:     3307
Database: smartprep
User:     smartprep
Password: <your configured DB password>

You can edit the status cell directly in the users table, or run:

UPDATE users
SET status = 'active'
WHERE username = 'YOUR_ADMIN_USERNAME';

After activation, return to SmartPrep Modern and log in with the administrator account.

Docker restoration

For the restored local environment, the backend can be run with Docker Compose while SmartPrep Modern remains a native Windows application.

The Docker setup runs:

smartprep-mysql

smartprep-api

smartprep-celery-worker

smartprep-celery-beat

It can reuse Redis already exposed through Docker Desktop/Windows on port 6379.

From the folder containing docker-compose.yml:

docker compose up -d --build

The API is then available at:

http://localhost:8000
http://localhost:8000/docs

MySQL is exposed to the host on port 3307, while the container itself uses the standard MySQL port 3306.

The initialization SQL under docker/mysql/init/ runs automatically only when the MySQL data volume is created for the first time. To intentionally rebuild the local database from the initialization SQL:

docker compose down -v
docker compose up -d --build

The restoration schema was reconstructed from the database relationships exercised by the preserved Python source. It should not be presented as the original lost schema; exact historical constraints, defaults, indexes, and field lengths may differ.

Environment variables

Variable

Purpose

Local example

DB_HOST

MySQL host

127.0.0.1

DB_PORT

Database port (reserved for local config)

3306

DB_USER

Database user

root

DB_PASSWORD

Database password

local value

DB_NAME

SmartPrep database

smartprep

CELERY_BROKER_URL

Redis/Celery connection

redis://localhost:6379/1

OLLAMA_HOST

Ollama-compatible server

http://localhost:11434

OLLAMA_MODEL

Model used for analysis

your installed model

EMAIL_SENDER

SMTP sender for recovery mail

optional

EMAIL_PASSWORD

SMTP/app password

optional

SMTP_SERVER

SMTP host

smtp.gmail.com

SMTP_PORT

SMTP port

587

Desktop client

The companion Windows client is available at:

https://github.com/SaintRelion/SmartPrepModern

Security

Secrets should never be committed to source control. SMTP credentials and external service configuration are loaded from environment variables in the local-ready version of this project.

If a credential was previously committed to Git history, rotate/revoke it before making the repository public; removing it from the latest file does not remove it from previous commits.

Engineering notes

This repository reflects a system delivered under a short development window and is preserved as an example of an end-to-end client/server implementation. Newer projects may use different abstractions or architecture as the author's engineering practices have continued to evolve.

Author

June Aurelius Jacinto
Full-Stack Software Developer

