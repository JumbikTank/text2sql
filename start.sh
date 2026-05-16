#!/bin/bash

# Text2SQL Development Startup Script
# This script starts both backend and frontend in development mode

set -e

# Add common Python/uv locations to PATH
export PATH="$HOME/.local/bin:$PATH"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Text2SQL Development Startup       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════╝${NC}"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found${NC}"
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    cp .env.example .env
    echo -e "${RED}❌ Please configure .env file before continuing${NC}"
    echo -e "${YELLOW}Edit .env and set:${NC}"
    echo -e "  - LLM_PROVIDER (oci, openai, anthropic, ollama)"
    echo -e "  - MODEL_ID"
    echo -e "  - API keys for your chosen provider"
    echo -e "  - Database credentials"
    exit 1
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check backend dependencies
echo -e "${BLUE}🔍 Checking backend dependencies...${NC}"
if ! command_exists uv; then
    echo -e "${RED}❌ uv not found. Please install: pip install uv${NC}"
    exit 1
fi
echo -e "${GREEN}✓ uv found${NC}"

# Check frontend dependencies
echo -e "${BLUE}🔍 Checking frontend dependencies...${NC}"
if ! command_exists node; then
    echo -e "${RED}❌ Node.js not found. Please install Node.js 18+${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js found: $(node --version)${NC}"

# Install backend dependencies
echo -e "${BLUE}📦 Installing backend dependencies...${NC}"
uv sync

# Install frontend dependencies
echo -e "${BLUE}📦 Installing frontend dependencies...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
fi
cd ..

# Create log directory
mkdir -p logs

# Start backend
echo -e "${GREEN}🚀 Starting backend (port 18001)...${NC}"
uv run python run.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > logs/backend.pid

# Wait for backend to start
echo -e "${YELLOW}⏳ Waiting for backend to start...${NC}"
MAX_RETRIES=10
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 1
    if curl -s http://localhost:18001/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend started successfully${NC}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "${RED}❌ Backend failed to start. Check logs/backend.log${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

# Start frontend
echo -e "${GREEN}🚀 Starting frontend (port 13000)...${NC}"
cd frontend
npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
cd ..

echo ""
echo -e "${GREEN}╔════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🎉 Text2SQL is now running!        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📍 Backend:  ${GREEN}http://localhost:18001${NC}"
echo -e "${BLUE}📍 Frontend: ${GREEN}http://localhost:13000${NC}"
echo -e "${BLUE}📍 API Docs: ${GREEN}http://localhost:18001/docs${NC}"
echo ""
echo -e "${YELLOW}📝 Logs:${NC}"
echo -e "   Backend:  tail -f logs/backend.log"
echo -e "   Frontend: tail -f logs/frontend.log"
echo ""
echo -e "${YELLOW}🛑 To stop:${NC}"
echo -e "   ./stop.sh"
echo ""
echo -e "${YELLOW}Press Ctrl+C to view logs (services will continue running)${NC}"

# Follow logs
trap 'echo -e "\n${YELLOW}Services are still running. Use ./stop.sh to stop them.${NC}"; exit 0' INT

tail -f logs/backend.log logs/frontend.log
