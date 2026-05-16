#!/bin/bash

# Text2SQL Stop Script
# This script stops both backend and frontend services

set -e

# Add common Python/uv locations to PATH
export PATH="$HOME/.local/bin:$PATH"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Stopping Text2SQL Services...      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════╝${NC}"
echo ""

# Stop backend
if [ -f logs/backend.pid ]; then
    BACKEND_PID=$(cat logs/backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        echo -e "${BLUE}🛑 Stopping backend (PID: $BACKEND_PID)...${NC}"
        kill $BACKEND_PID
        echo -e "${GREEN}✓ Backend stopped${NC}"
    else
        echo -e "${RED}❌ Backend not running${NC}"
    fi
    rm logs/backend.pid
else
    echo -e "${RED}❌ Backend PID file not found${NC}"
fi

# Stop frontend
if [ -f logs/frontend.pid ]; then
    FRONTEND_PID=$(cat logs/frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        echo -e "${BLUE}🛑 Stopping frontend (PID: $FRONTEND_PID)...${NC}"
        kill $FRONTEND_PID
        # Also kill child processes (Vite)
        pkill -P $FRONTEND_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Frontend stopped${NC}"
    else
        echo -e "${RED}❌ Frontend not running${NC}"
    fi
    rm logs/frontend.pid
else
    echo -e "${RED}❌ Frontend PID file not found${NC}"
fi

# Kill any remaining processes on Text2SQL's ports (new + legacy values).
echo -e "${BLUE}🔍 Checking for remaining processes...${NC}"
lsof -ti:18001 | xargs kill -9 2>/dev/null || true
lsof -ti:13000 | xargs kill -9 2>/dev/null || true
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:8001 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ All services stopped${NC}"
