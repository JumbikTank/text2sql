# Text2SQL — естественный язык в SQL

Задавайте вопросы своей PostgreSQL-базе на обычном русском (или английском) —
Text2SQL подбирает релевантные таблицы, генерирует SQL-запрос на чтение,
выполняет его и возвращает как предпросмотр результата, так и CSV для скачивания.

Стек:
- **Бэкенд** — Litestar + LangGraph + LangChain; PostgreSQL с pgvector для
  эмбеддингов описаний таблиц; асинхронный SQLAlchemy.
- **Фронтенд** — React 18 + Vite + Zustand + React Query + Tailwind.
- **LLM-провайдеры** — OCI Generative AI, OpenAI, Anthropic, Google или Ollama.

## Быстрый старт

### Требования

- Python 3.13+ и [uv](https://github.com/astral-sh/uv)
- Node.js 18+
- Docker (для тестового Postgres) или уже установленный PostgreSQL 14+ с `pgvector`

### 1. Поднять Postgres с pgvector

```bash
docker compose -f docker-compose.test.yml up -d
```

Поднимется Postgres на `localhost:5433` (база `testdb`, пользователь `testuser`,
пароль `testpass`) с расширением `vector` и предзаполненной демо-схемой.

Этот шаг можно пропустить, если у вас уже есть PostgreSQL, к которому
вы хотите подключиться.

### 2. Настроить `.env`

```bash
cp .env.example .env
```

Откройте `.env` и задайте как минимум следующее:

```env
# База данных
USERNAME=testuser
PASSWORD=testpass
DB_HOST=localhost
DB_PORT=5433
DATABASE=testdb

# LLM (выберите одного провайдера)
LLM_PROVIDER=openai
MODEL_ID=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Приложение
PORT=18001
HOST=127.0.0.1
CSV_DOWNLOAD_BASE_URL=http://localhost:18001/files/csv

# Нужен для шифрования сохранённых credentials подключений на диске.
# Сгенерировать ключ:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIAL_ENCRYPTION_KEY=<вставьте-сгенерированный-fernet-ключ>
```

Настройки для OCI / Anthropic / Google / Ollama — в разделе ниже.

### 3. Установить зависимости и запустить бэкенд

```bash
uv sync
uv run python run.py
```

API будет доступен по адресу `http://127.0.0.1:18001`; OpenAPI-схема —
`http://127.0.0.1:18001/schema/openapi.json`.

### 4. Установить зависимости и запустить фронтенд

```bash
cd frontend
npm install
npm run dev
```

Откройте `http://localhost:13000`. Vite проксирует `/api`, `/ws` и `/files` на
бэкенд, так что прописывать URL бэкенда в UI не нужно.

### 5. Добавить подключение через UI

1. Нажмите на кнопку статуса подключения (правый верхний угол) → **Add Connection**.
2. Заполните host / port / database / user / password.
3. Нажмите **Test Connection** для проверки, затем **Save**.
4. В списке подключений откройте меню (⋮) у нужного подключения и выберите
   **Set Active**. Браузер схемы заполнится — можно задавать вопросы.

Первый вопрос к подключению запускает фоновое сканирование, которое
эмбеддит имя, описание и колонки каждой таблицы в таблицу `notes_<id>` —
последующие вопросы используют эти эмбеддинги, чтобы выбирать релевантные
таблицы.

## Настройка LLM-провайдеров

Задайте `LLM_PROVIDER`, `MODEL_ID` и ключи конкретного провайдера:

```env
# OpenAI
LLM_PROVIDER=openai
MODEL_ID=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Anthropic
LLM_PROVIDER=anthropic
MODEL_ID=claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...

# Google (Gemini)
LLM_PROVIDER=google
MODEL_ID=gemini-2.5-flash
GOOGLE_API_KEY=...

# Oracle Cloud (OCI Generative AI)
LLM_PROVIDER=oci
MODEL_ID=cohere.command-r-plus
COMPARTMENT_ID=ocid1.compartment.oc1..your-id
SERVICE_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
AUTH_FILE_LOCATION=~/.oci/config
AUTH_PROFILE=DEFAULT

# Ollama (локально)
LLM_PROVIDER=ollama
MODEL_ID=llama3
OLLAMA_BASE_URL=http://localhost:11434
```

## Разработка

```bash
# Бэкенд
uv run pytest                 # запустить тесты
uv run ruff check . --fix     # линтер
uv run ruff format .          # форматирование
uv run pyright                # проверка типов

# Фронтенд
cd frontend
npm run test                  # vitest (watch-режим)
npm run test:run              # vitest (один прогон)
npm run type-check            # tsc --noEmit
npm run lint                  # eslint
```

### Docker

```bash
make build
make up        # запустить бэкенд в prod-режиме на :18001
make dev       # запустить с live reload
make logs
make down
```

`docker-compose.yml` поднимает только бэкенд. Фронтенд запускается отдельно
через `npm run dev`, либо собирается статикой (`npm run build`) и
раздаётся через любой reverse proxy, проксирующий `/api`, `/ws` и `/files`
на бэкенд.

## Как это работает

```
Вопрос пользователя
      ↓
MessageService (кэшируется по подключению в app.state)
      ↓
Агент выбирает инструмент:
  - generate_sql_query  → векторный поиск → фильтр LLM → создание SQL
                          → контроллер → выполнение
  - show_table          → то же самое, но результат выгружается как CSV
  - follow_up           → переиспользует ранее найденные таблицы,
                          переписывает предыдущий SQL
      ↓
Ответ на естественном языке + SQL + ссылка на CSV
```

Бэкенд кэширует инициализированный конвейер агента (LLM-клиент, движок БД,
векторное хранилище, описания таблиц, контроллер) по идентификатору активного
подключения. Первый запрос к подключению несёт стоимость инициализации;
последующие запросы переиспользуют её.

## Замечания по безопасности

- `/api/sql` и `/api/messages` выполняют запросы под учётными данными активного
  подключения. Создайте отдельную **read-only** роль PostgreSQL для Text2SQL и
  выдайте ей только нужные привилегии SELECT. Встроенный denylist блокирует
  основные пишущие конструкции, но не заменяет права на уровне СУБД.
- В приложении сейчас **нет аутентификации**. Привязывайте его к `127.0.0.1`
  или ставьте за reverse proxy с авторизацией, прежде чем выставлять наружу.
- Сохранённые credentials подключений лежат в `data/connections.enc`,
  зашифрованные ключом Fernet из `CREDENTIAL_ENCRYPTION_KEY`. Потеря ключа
  означает потерю сохранённых данных.

## Структура проекта

```
src/
├── api/            # Обработчики маршрутов Litestar (messages, sql, schema, websocket, health, mock)
├── agents/         # Оркестратор агента и инструменты LangGraph
│   └── tools/      # generate_sql_query / show_table / follow_up + SQL creator, controller, executor
├── common/         # Настройки, DTO, исключения, обработчик ошибок, логгер, хранилище credentials
├── llm/            # Фабрика провайдеров и реализации (OCI, OpenAI, Anthropic, Google, Ollama)
└── services/       # Сервисы подключений, сканера, планировщика, эмбеддингов

frontend/src/
├── components/     # UI-компоненты (чат, подключения, схема, базовые ui-примитивы, ErrorBoundary)
├── hooks/          # useChat, useConnection, useSchema, useWebSocket
├── services/       # axios API-клиент
├── store/          # Zustand-стораджи (chat, connection, schema, notification)
└── utils/          # cn, download, csv
```
