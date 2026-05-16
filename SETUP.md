# Text2SQL Setup Guide

Полная инструкция по запуску проекта (Backend + Frontend).

## Системные требования

### Backend
- Python 3.13+
- uv (менеджер пакетов Python)
- MySQL HeatWave (или другая БД)

### Frontend
- Node.js 18+ или Bun
- npm/yarn/pnpm/bun

## 🚀 Быстрый старт

### 1. Backend Setup

```bash
# Установить зависимости
uv sync

# Настроить .env файл
cp .env.example .env
# Отредактировать .env:
# - Выбрать LLM_PROVIDER (oci, openai, anthropic, ollama)
# - Добавить credentials для выбранного провайдера
# - Настроить подключение к БД

# Запустить backend
uv run python run.py
# Backend будет доступен на http://localhost:8000
```

### 2. Frontend Setup

```bash
# Перейти в директорию frontend
cd frontend

# Установить зависимости
npm install
# или
yarn install
# или
pnpm install
# или
bun install

# Запустить dev сервер
npm run dev
# Frontend будет доступен на http://localhost:3000
```

## 🔧 Подробная настройка

### Backend Configuration

#### Выбор LLM провайдера

**Option 1: Oracle Cloud (OCI)**
```env
LLM_PROVIDER=oci
MODEL_ID=cohere.command-r-plus
COMPARTMENT_ID=ocid1.compartment.oc1..your-id
SERVICE_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
AUTH_FILE_LOCATION=../.oci/config
AUTH_PROFILE=DEFAULT
```

**Option 2: OpenAI**
```env
LLM_PROVIDER=openai
MODEL_ID=gpt-4
OPENAI_API_KEY=sk-your-api-key
```

**Option 3: Anthropic (Claude)**
```env
LLM_PROVIDER=anthropic
MODEL_ID=claude-3-opus-20240229
ANTHROPIC_API_KEY=sk-ant-your-api-key
```

**Option 4: Ollama (Local)**
```env
LLM_PROVIDER=ollama
MODEL_ID=llama3
OLLAMA_BASE_URL=http://localhost:11434
```

#### Database Configuration

```env
USERNAME=your_db_user
PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=3306
DATABASE=your_database
```

### Frontend Configuration

Frontend автоматически проксирует запросы к backend через Vite:

```typescript
// vite.config.ts
server: {
  port: 3000,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

## 🐳 Docker Setup (опционально)

```bash
# Backend
make build   # Собрать образ
make up      # Запустить в production mode
make dev     # Запустить в development mode

# Frontend (добавить в docker-compose.yml)
# TODO: Добавить frontend service в docker-compose
```

## 📝 Development Workflow

### Backend

```bash
# Запуск в dev режиме
uv run python run.py

# Линтинг
uv run ruff check . --fix
uv run ruff format .

# Type checking
uv run pyright

# Тесты
uv run pytest
```

### Frontend

```bash
cd frontend

# Dev режим с hot reload
npm run dev

# Type checking
npm run type-check

# Линтинг
npm run lint

# Production build
npm run build
npm run preview
```

## 🌐 API Endpoints

### Backend (Port 8000)

- `GET /health` - Health check
- `POST /api/messages` - Send chat messages
- `GET /api/docs` - OpenAPI documentation
- `GET /files/csv/{filename}` - Download CSV files

### Frontend (Port 3000)

- `/` - Main chat interface

## 🎨 Features

### Backend
- ✅ Multiple LLM providers (OCI, OpenAI, Anthropic, Ollama)
- ✅ Vector search for table discovery
- ✅ SQL generation with safety guardrails
- ✅ Read-only query execution
- ✅ CSV export
- ✅ Context-aware follow-up questions

### Frontend
- ✅ ChatGPT-like interface
- ✅ Markdown rendering
- ✅ SQL syntax highlighting
- ✅ CSV download
- ✅ Dark mode
- ✅ Responsive design
- ✅ Smooth animations
- ✅ Error handling

## 🔍 Troubleshooting

### Backend Issues

**Problem: LLM connection fails**
```bash
# Проверить credentials
cat .env | grep API_KEY

# Для OCI проверить конфиг
cat ~/.oci/config

# Проверить health endpoint
curl http://localhost:8000/health
```

**Problem: Database connection fails**
```bash
# Проверить подключение к БД
mysql -h localhost -u your_user -p your_database

# Проверить настройки в .env
cat .env | grep DB_
```

### Frontend Issues

**Problem: API requests fail**
```bash
# Проверить что backend запущен
curl http://localhost:8000/health

# Проверить proxy в vite.config.ts
# Перезапустить dev сервер
npm run dev
```

**Problem: Build fails**
```bash
# Очистить node_modules и переустановить
rm -rf node_modules
npm install

# Проверить TypeScript errors
npm run type-check
```

## 📚 Documentation

- [Backend Documentation](./CLAUDE.md)
- [Frontend Documentation](./frontend/README.md)
- [API Documentation](http://localhost:8000/docs) - после запуска backend

## 🤝 Contributing

1. Создать feature branch
2. Следовать code style (backend: ruff, frontend: eslint)
3. Добавить type hints (Python) и types (TypeScript)
4. Тестировать изменения
5. Создать Pull Request

## 📄 License

MIT License (или как указано в проекте)
