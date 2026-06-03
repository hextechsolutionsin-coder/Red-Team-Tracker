# Red Team Operations Tracker

A lightweight internal web application for SOC red teams to manage engagements, track findings with MITRE ATT&CK tagging, maintain a full operator audit log, and export PDF reports.

**Stack:** FastAPI · PostgreSQL · Vanilla JS · nginx · Docker Compose

---

## Features

- **Role-based access control** — Admin, Lead, Operator
- **Engagement management** — lifecycle tracking (planned → active → completed → archived)
- **Finding management** — severity classification, MITRE ATT&CK tagging, evidence file attachments
- **Operator audit log** — append-only record of all actions
- **PDF report generation** — per-engagement reports with findings ordered by severity
- **Session-based authentication** — server-side sessions with 8-hour inactivity timeout

---

## Deploying on Windows Server

### Prerequisites

Install the following on your Windows Server machine:

1. **Docker Desktop for Windows**
   - Download from: https://www.docker.com/products/docker-desktop/
   - Enable **WSL 2 backend** during installation (recommended)
   - After install, open Docker Desktop and wait until it shows "Engine running"

2. **Git for Windows** (to clone the repo)
   - Download from: https://git-scm.com/download/win

---

### Step 1 — Clone the repository

Open **PowerShell** or **Command Prompt** and run:

```powershell
git clone https://github.com/hextechsolutionsin-coder/Red-Team-Tracker.git
cd Red-Team-Tracker
```

---

### Step 2 — Create the environment file

Copy the example and fill in your values:

```powershell
copy .env.example .env
notepad .env
```

Required values to set in `.env`:

```env
# A long random string used to sign session cookies — change this!
SESSION_SECRET=change-me-to-a-long-random-string

# PostgreSQL password
DB_PASSWORD=your-strong-db-password

# Full database URL (update password to match DB_PASSWORD above)
DATABASE_URL=postgresql+asyncpg://redboard:your-strong-db-password@db:5432/redboard

# Directory inside the backend container where uploaded evidence files are stored
UPLOAD_DIR=/uploads

# Allowed CORS origins (set to your server IP or domain)
ALLOWED_ORIGINS=http://localhost

# Ports (defaults: frontend on 80, backend on 8000)
FRONTEND_PORT=80
API_PORT=8000
```

> **Security note:** Never commit your `.env` file to version control.

---

### Step 3 — Build and start the stack

```powershell
docker compose up --build -d
```

This will:
1. Build the FastAPI backend image
2. Build the nginx frontend image
3. Start PostgreSQL
4. Run Alembic database migrations automatically
5. Start all three services

The first build takes 3–5 minutes. Subsequent starts are fast.

---

### Step 4 — Verify everything is running

```powershell
docker compose ps
```

All three services (`db`, `backend`, `frontend`) should show **healthy**.

Check the backend health endpoint:

```powershell
curl http://localhost:8000/api/v1/health
# Expected: {"status":"ok"}
```

---

### Step 5 — Access the application

Open a browser and navigate to:

```
http://localhost
```

or replace `localhost` with your server's IP address or hostname.

---

### Creating the first admin user

The application has no default users. Create the first admin directly in the database:

```powershell
docker compose exec backend python -c "
import asyncio, uuid
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models.user import User
import bcrypt

async def create_admin():
    pw = bcrypt.hashpw(b'YourPassword123!', bcrypt.gensalt(rounds=12)).decode()
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username='admin',
            password_hash=pw,
            role='admin',
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        db.add(user)
        await db.commit()
        print('Admin user created.')

asyncio.run(create_admin())
"
```

Change `YourPassword123!` to a strong password before running.

---

### Stopping the application

```powershell
# Stop without removing data
docker compose stop

# Stop and remove containers (keeps database volume)
docker compose down

# Stop and remove everything including the database
docker compose down -v
```

---

### Updating to a new version

```powershell
git pull
docker compose up --build -d
```

Alembic migrations run automatically on startup.

---

## Running Tests

Tests require Python 3.11+ and the backend dependencies installed locally:

```powershell
cd backend
pip install -r requirements.txt
pytest tests/ --asyncio-mode=auto
```

Expected output: all tests pass, a small number skip (Docker smoke tests require Docker CLI access; PDF tests skip if WeasyPrint is not installed locally).

---

## Directory Structure

```
Red-Team-Tracker/
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── routers/        # API route handlers
│   │   ├── schemas/        # Pydantic request/response models
│   │   ├── services/       # Business logic helpers
│   │   ├── templates/      # Jinja2 HTML template for PDF reports
│   │   ├── config.py       # Environment variable settings
│   │   ├── database.py     # Async SQLAlchemy engine
│   │   ├── dependencies.py # Auth/session/RBAC dependencies
│   │   ├── errors.py       # Standardised error response format
│   │   └── main.py         # FastAPI app entry point
│   ├── tests/              # pytest test suite
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/               # Vanilla HTML/CSS/JS frontend
│   ├── *.html              # Application pages
│   ├── js/                 # JavaScript modules
│   ├── css/                # Application styles
│   ├── vendor/             # Bootstrap, Font Awesome, Chart.js, jQuery
│   └── Dockerfile
├── nginx/
│   └── nginx.conf          # Reverse proxy + static file server config
├── alembic/                # Database migration scripts
├── docker-compose.yml
└── .env.example            # Environment variable template
```

---

## Default Ports

| Service  | Port |
|----------|------|
| Frontend (nginx) | 80 |
| Backend (FastAPI) | 8000 |
| PostgreSQL | 5432 (internal only) |

Ports are overridable via `FRONTEND_PORT` and `API_PORT` in `.env`.

---

## Troubleshooting

**Backend fails to start:**
```powershell
docker compose logs backend
```
Common causes: missing `SESSION_SECRET` in `.env`, database connection failure.

**Port 80 already in use:**
Change `FRONTEND_PORT=8080` in `.env` and access the app at `http://localhost:8080`.

**Database migration failed:**
```powershell
docker compose logs backend | findstr "alembic"
docker compose down -v
docker compose up --build -d
```

**Reset everything (destructive — deletes all data):**
```powershell
docker compose down -v
docker compose up --build -d
```
