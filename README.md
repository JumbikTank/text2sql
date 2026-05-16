# Text2SQL — Natural Language to SQL

Ask questions about your PostgreSQL database in plain English (or Russian); Text2SQL
picks the relevant tables, generates a read-only SQL query, runs it, and returns
both the result preview and a CSV you can download.

Stack:
- **Backend** — Litestar + LangGraph + LangChain; PostgreSQL with pgvector for
  table-description embeddings; async SQLAlchemy.
- **Frontend** — React 18 + Vite + Zustand + React Query + Tailwind.
- **LLM providers** — OCI Generative AI, OpenAI, Anthropic, or Ollama.

## Quickstart

### Prerequisites

- Python 3.13+ and [uv](https://github.com/astral-sh/uv)
- Node.js 18+
- Docker (for the test Postgres) or an existing PostgreSQL 14+ with `pgvector`

### 1. Start a Postgres with pgvector

```bash
docker compose -f docker-compose.test.yml up -d
```

This gives you a Postgres at `localhost:5433` (db `testdb`, user `testuser`,
password `testpass`) with the `vector` extension and a seeded sample schema.

Skip this step if you already have a Postgres you want to use.

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
# Database
USERNAME=testuser
PASSWORD=testpass
DB_HOST=localhost
DB_PORT=5433
DATABASE=testdb

# LLM (pick one provider)
LLM_PROVIDER=openai
MODEL_ID=gpt-4o-mini
OPENAI_API_KEY=sk-...

# App
PORT=18001
HOST=127.0.0.1
CSV_DOWNLOAD_BASE_URL=http://localhost:18001/files/csv

# Required to encrypt saved connection credentials on disk.
# Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIAL_ENCRYPTION_KEY=<paste-generated-fernet-key>
```

See the LLM provider sections below for OCI / Anthropic / Ollama options.

### 3. Install deps and start the backend

```bash
uv sync
uv run python run.py
```

The API is available on `http://127.0.0.1:18001`; OpenAPI schema at
`http://127.0.0.1:18001/schema/openapi.json`.

### 4. Install deps and start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:13000`. Vite proxies `/api`, `/ws`, and `/files` to the
backend, so you never need to configure the backend URL in the UI.

### 5. Add a connection in the UI

1. Click the connection status button (top right) → **Add Connection**.
2. Fill in host / port / database / user / password.
3. Click **Test Connection** to verify, then **Save**.
4. In the connection list, open the menu (⋮) on your connection and click
   **Set Active**. The table browser populates and you can ask questions.

The first question against a connection triggers a background scan that
embeds each table's name, description, and columns into the `notes_<id>` table
— subsequent questions use those embeddings to pick relevant tables.

## LLM provider setup

Set `LLM_PROVIDER` and `MODEL_ID`, plus the provider-specific keys:

```env
# OpenAI
LLM_PROVIDER=openai
MODEL_ID=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Anthropic
LLM_PROVIDER=anthropic
MODEL_ID=claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...

# Oracle Cloud (OCI Generative AI)
LLM_PROVIDER=oci
MODEL_ID=cohere.command-r-plus
COMPARTMENT_ID=ocid1.compartment.oc1..your-id
SERVICE_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
AUTH_FILE_LOCATION=~/.oci/config
AUTH_PROFILE=DEFAULT

# Ollama (local)
LLM_PROVIDER=ollama
MODEL_ID=llama3
OLLAMA_BASE_URL=http://localhost:11434
```

## Development

```bash
# Backend
uv run pytest                 # run tests
uv run ruff check . --fix     # lint
uv run ruff format .          # format
uv run pyright                # type check

# Frontend
cd frontend
npm run test                  # vitest (watch)
npm run test:run              # vitest (single run)
npm run type-check            # tsc --noEmit
npm run lint                  # eslint
```

### Docker

```bash
make build
make up        # start backend in prod mode on :18001
make dev       # start with live reload
make logs
make down
```

`docker-compose.yml` only starts the backend. Run the frontend separately with
`npm run dev`, or build a static bundle (`npm run build`) and serve it behind
any reverse proxy that forwards `/api`, `/ws`, and `/files` to the backend.

## How it works

```
User question
      ↓
MessageService (cached per connection in app.state)
      ↓
Agent decides tool:
  - generate_sql_query  → vector search → LLM filter → SQL create → controller → execute
  - show_table          → same, but formats results as a downloadable CSV
  - follow_up           → reuses previously retrieved tables, rewrites last SQL
      ↓
Natural-language answer + SQL + CSV download link
```

The backend caches the initialized agent pipeline (LLM client, DB engine,
vector store, table descriptions, controller) per active connection id. The
first request for a given connection pays the initialization cost; subsequent
requests reuse it.

## Safety notes

- `/api/sql` and `/api/messages` run queries with your active connection's
  credentials. Create a **read-only** PostgreSQL role for Text2SQL and grant it
  only the SELECT privileges it needs. The built-in denylist blocks common
  write statements but is not a substitute for database-level permissions.
- The app currently has **no authentication**. Bind it to `127.0.0.1` or put it
  behind an authenticated reverse proxy before exposing it beyond localhost.
- Saved connection credentials live in `data/connections.enc`, encrypted with
  the Fernet key from `CREDENTIAL_ENCRYPTION_KEY`. Losing the key means
  losing the stored credentials.

## Project layout

```
src/
├── api/            # Litestar route handlers (messages, sql, schema, websocket, health, mock)
├── agents/         # Agent orchestrator and LangGraph tools
│   └── tools/      # generate_sql_query / show_table / follow_up + SQL creator, controller, executor
├── common/         # Settings, DTOs, exceptions, error handler, logger, credential storage
├── llm/            # Provider factory + implementations (OCI, OpenAI, Anthropic, Ollama)
└── services/       # Connection, scanner, scheduler, embedding services

frontend/src/
├── components/     # UI components (chat, connection, schema, ui primitives, ErrorBoundary)
├── hooks/          # useChat, useConnection, useSchema, useWebSocket
├── services/       # axios API client
├── store/          # Zustand stores (chat, connection, schema, notification)
└── utils/          # cn, download, csv
```
