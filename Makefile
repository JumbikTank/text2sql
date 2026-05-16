.PHONY: help build up down restart logs shell test clean dev prod status ps exec

# Variables
COMPOSE := docker compose
COMPOSE_FILE := docker-compose.yml
SERVICE := api
IMAGE_NAME := text2sql-be
CONTAINER_NAME := text2sql-api

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Default target
help: ## Show this help message
	@echo '${GREEN}Available commands:${NC}'
	@echo ''
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  ${YELLOW}%-15s${NC} %s\n", $$1, $$2}'
	@echo ''
	@echo '${GREEN}Examples:${NC}'
	@echo '  make build       # Build Docker image'
	@echo '  make up          # Start services'
	@echo '  make dev         # Start in development mode'
	@echo '  make prod-local  # Run production locally (no Docker)'
	@echo '  make stop-local  # Stop local production server'
	@echo '  make test-api    # Test API endpoints'

# Docker commands
build: ## Build Docker image
	@echo "${GREEN}Building Docker image...${NC}"
	$(COMPOSE) build --no-cache

build-cache: ## Build Docker image with cache
	@echo "${GREEN}Building Docker image with cache...${NC}"
	$(COMPOSE) build

up: ## Start services in production mode
	@echo "${GREEN}Starting services in production mode...${NC}"
	$(COMPOSE) up -d
	@echo "${GREEN}Services started. API available at http://localhost:8001${NC}"

dev: ## Start services in development mode with live reload
	@echo "${GREEN}Starting services in development mode...${NC}"
	$(COMPOSE) up

dev-bg: ## Start services in development mode in background
	@echo "${GREEN}Starting services in development mode (background)...${NC}"
	$(COMPOSE) up -d
	@echo "${GREEN}Services started. API available at http://localhost:8001${NC}"

down: ## Stop and remove containers
	@echo "${YELLOW}Stopping services...${NC}"
	$(COMPOSE) down

down-volumes: ## Stop services and remove volumes
	@echo "${RED}Stopping services and removing volumes...${NC}"
	$(COMPOSE) down -v

restart: ## Restart services
	@echo "${YELLOW}Restarting services...${NC}"
	$(COMPOSE) restart

stop: ## Stop services without removing
	@echo "${YELLOW}Stopping services...${NC}"
	$(COMPOSE) stop

start: ## Start existing containers
	@echo "${GREEN}Starting existing containers...${NC}"
	$(COMPOSE) start

logs: ## Show logs
	$(COMPOSE) logs -f

logs-api: ## Show API logs only
	$(COMPOSE) logs -f $(SERVICE)

shell: ## Open shell in API container
	@echo "${GREEN}Opening shell in API container...${NC}"
	$(COMPOSE) exec $(SERVICE) /bin/bash

exec: ## Execute command in API container (use with CMD="command")
	@if [ -z "$(CMD)" ]; then \
		echo "${RED}Please specify CMD=\"command\"${NC}"; \
		exit 1; \
	fi
	$(COMPOSE) exec $(SERVICE) $(CMD)

ps: ## Show running containers
	$(COMPOSE) ps

status: ## Show detailed status
	@echo "${GREEN}Container Status:${NC}"
	@$(COMPOSE) ps
	@echo ""
	@echo "${GREEN}Port Bindings:${NC}"
	@docker ps --format "table {{.Names}}\t{{.Ports}}" | grep -E "(NAMES|$(CONTAINER_NAME))" || true
	@echo ""
	@echo "${GREEN}Health Status:${NC}"
	@docker inspect --format='{{.State.Health.Status}}' $(CONTAINER_NAME) 2>/dev/null || echo "Container not running"

# Testing
test-api: ## Test API endpoints
	@echo "${GREEN}Testing API endpoints...${NC}"
	@echo "Testing mock messages endpoint..."
	@curl -X POST http://localhost:8001/api/mock/messages \
		-H "Content-Type: application/json" \
		-d '{"messages": [{"role": "user", "content": "Show me SQL for top customers"}]}' \
		-s | python3 -m json.tool || echo "${RED}Mock messages endpoint failed${NC}"
	@echo ""
	@echo "Testing mock SQL endpoint..."
	@curl -X POST http://localhost:8001/api/mock/sql \
		-H "Content-Type: application/json" \
		-d '{"sql": "SELECT * FROM users LIMIT 10;"}' \
		-s | python3 -m json.tool || echo "${RED}Mock SQL endpoint failed${NC}"
	@echo ""
	@echo "Testing health endpoint..."
	@curl -f http://localhost:8001/health -s || echo "${RED}Health check failed${NC}"

test-api-docker: ## Test API endpoints for Docker (port 8000)
	@echo "${GREEN}Testing Docker API endpoints...${NC}"
	@echo "Testing mock messages endpoint..."
	@curl -X POST http://localhost:8000/api/mock/messages \
		-H "Content-Type: application/json" \
		-d '{"messages": [{"role": "user", "content": "Show me SQL for top customers"}]}' \
		-s | python3 -m json.tool || echo "${RED}Mock messages endpoint failed${NC}"
	@echo ""
	@echo "Testing mock SQL endpoint..."
	@curl -X POST http://localhost:8000/api/mock/sql \
		-H "Content-Type: application/json" \
		-d '{"sql": "SELECT * FROM users LIMIT 10;"}' \
		-s | python3 -m json.tool || echo "${RED}Mock SQL endpoint failed${NC}"
	@echo ""
	@echo "Testing health endpoint..."
	@curl -f http://localhost:8000/health -s || echo "${RED}Health check failed${NC}"

health: ## Check health status
	@curl -f http://localhost:8001/health && echo "${GREEN}✓ API is healthy${NC}" || echo "${RED}✗ API is not healthy${NC}"

health-docker: ## Check health status for Docker
	@curl -f http://localhost:8000/health && echo "${GREEN}✓ Docker API is healthy${NC}" || echo "${RED}✗ Docker API is not healthy${NC}"

# Maintenance
clean: ## Clean up everything (containers, images, volumes)
	@echo "${RED}Cleaning up Docker resources...${NC}"
	$(COMPOSE) down -v
	docker rmi $(IMAGE_NAME):latest 2>/dev/null || true
	@echo "${GREEN}Cleanup complete${NC}"

prune: ## Prune unused Docker resources
	@echo "${YELLOW}Pruning unused Docker resources...${NC}"
	docker system prune -f

rebuild: clean build up ## Clean rebuild and start
	@echo "${GREEN}Rebuild complete${NC}"

# Development helpers
install-local: ## Install dependencies locally
	@if command -v uv >/dev/null 2>&1; then \
		echo "${GREEN}Installing with uv...${NC}"; \
		uv sync; \
	else \
		echo "${GREEN}Installing with pip...${NC}"; \
		pip install -r requirements.txt 2>/dev/null || echo "${YELLOW}requirements.txt not found, please install dependencies manually${NC}"; \
	fi

run-local: ## Run application locally
	@if command -v uv >/dev/null 2>&1; then \
		uv run python run.py; \
	else \
		python3 run.py; \
	fi

prod-local: ## Run production server locally without Docker
	@echo "${GREEN}Starting production server locally (without Docker)...${NC}"
	@echo "Setting production environment variables..."
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	export ENVIRONMENT=production && \
	export DEBUG=false && \
	export LOG_LEVEL=INFO && \
	export HOST=0.0.0.0 && \
	export PORT=8001 && \
	uv run python run.py

stop-local: ## Stop local production server
	@echo "${YELLOW}Stopping local production server...${NC}"
	@pkill -f "uv run python run.py" || echo "${YELLOW}No local server process found${NC}"
	@echo "${GREEN}Local server stopped${NC}"

restart-local: stop-local prod-local ## Restart local production server
	@echo "${GREEN}Local server restarted${NC}"

format: ## Format code with ruff
	uv run ruff format .

lint: ## Lint code with ruff
	uv run ruff check .

lint-fix: ## Fix linting issues
	uv run ruff check . --fix

typecheck: ## Run type checking with pyright
	uv run pyright

# Docker debugging
inspect: ## Inspect API container
	docker inspect $(CONTAINER_NAME)

top: ## Show running processes in container
	docker top $(CONTAINER_NAME)

stats: ## Show container resource usage
	docker stats $(CONTAINER_NAME)

# Shortcuts
u: up ## Shortcut for up
d: down ## Shortcut for down
r: restart ## Shortcut for restart
l: logs ## Shortcut for logs
s: shell ## Shortcut for shell
t: test-api ## Shortcut for test-api