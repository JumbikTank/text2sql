#!/usr/bin/env bash

# Text2SQL Backend Management Script
# Usage: ./manage.sh [command] [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE="docker compose"
COMPOSE_FILE="docker-compose.yml"
SERVICE="api"
CONTAINER_NAME="text2sql-api"

# Helper functions
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running"
        exit 1
    fi

    print_success "Docker is running"
}

check_compose() {
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose v2 is not installed"
        exit 1
    fi
    print_success "Docker Compose v2 is available"
}

# Commands
cmd_build() {
    print_info "Building Docker image..."
    $COMPOSE build $@
    print_success "Build complete"
}

cmd_up() {
    print_info "Starting services in production mode..."
    $COMPOSE up -d
    print_success "Services started"
    print_info "API available at http://localhost:8001"
    print_info "OpenAPI docs at http://localhost:8001/docs"
}

cmd_dev() {
    print_info "Starting services in development mode..."
    $COMPOSE up
}

cmd_down() {
    print_warning "Stopping services..."
    $COMPOSE down $@
    print_success "Services stopped"
}

cmd_restart() {
    print_info "Restarting services..."
    cmd_down
    cmd_up
    print_success "Services restarted"
}

cmd_stop() {
    print_warning "Stopping services..."
    $COMPOSE stop
    print_success "Services stopped"
}

cmd_start() {
    print_info "Starting services..."
    $COMPOSE start
    print_success "Services started"
}

cmd_logs() {
    $COMPOSE logs -f $@
}

cmd_shell() {
    print_info "Opening shell in container..."
    $COMPOSE exec $SERVICE /bin/bash
}

cmd_status() {
    echo -e "${GREEN}=== Container Status ===${NC}"
    $COMPOSE ps

    echo -e "\n${GREEN}=== Health Check ===${NC}"
    if docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null | grep -q healthy; then
        print_success "API is healthy"
    else
        print_warning "API health check pending or failed"
    fi

    echo -e "\n${GREEN}=== Port Bindings ===${NC}"
    docker ps --format "table {{.Names}}\t{{.Ports}}" | grep -E "(NAMES|$CONTAINER_NAME)" || true
}

cmd_test() {
    print_info "Testing API endpoints..."

    # Wait for service to be ready
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -f http://localhost:8001/health -s &>/dev/null; then
            print_success "API is ready"
            break
        fi
        attempt=$((attempt + 1))
        if [ $attempt -eq $max_attempts ]; then
            print_error "API failed to become ready"
            exit 1
        fi
        sleep 1
    done

    echo -e "\n${BLUE}Testing mock messages endpoint...${NC}"
    curl -X POST http://localhost:8001/api/mock/messages \
        -H "Content-Type: application/json" \
        -d '{"messages": [{"role": "user", "content": "Show me SQL for top customers"}]}' \
        -s | python3 -m json.tool || print_error "Mock messages endpoint failed"

    echo -e "\n${BLUE}Testing mock SQL endpoint...${NC}"
    curl -X POST http://localhost:8001/api/mock/sql \
        -H "Content-Type: application/json" \
        -d '{"sql": "SELECT * FROM users LIMIT 10;"}' \
        -s | python3 -m json.tool || print_error "Mock SQL endpoint failed"

    print_success "API tests complete"
}

cmd_clean() {
    print_warning "Cleaning up Docker resources..."
    $COMPOSE down -v
    docker rmi ${CONTAINER_NAME}:latest 2>/dev/null || true
    print_success "Cleanup complete"
}

cmd_help() {
    cat << EOF
${GREEN}Text2SQL Backend Management Script${NC}

${YELLOW}Usage:${NC}
  ./manage.sh [command] [options]

${YELLOW}Commands:${NC}
  ${BLUE}build${NC}     Build Docker image
  ${BLUE}up${NC}        Start services in production mode
  ${BLUE}dev${NC}       Start services in development mode
  ${BLUE}down${NC}      Stop and remove containers
  ${BLUE}restart${NC}   Restart services
  ${BLUE}stop${NC}      Stop services (without removing)
  ${BLUE}start${NC}     Start existing containers
  ${BLUE}logs${NC}      Show logs (follow mode)
  ${BLUE}shell${NC}     Open shell in API container
  ${BLUE}status${NC}    Show detailed status
  ${BLUE}test${NC}      Test API endpoints
  ${BLUE}clean${NC}     Clean up everything
  ${BLUE}help${NC}      Show this help message

${YELLOW}Examples:${NC}
  ./manage.sh build         # Build Docker image
  ./manage.sh up            # Start in production
  ./manage.sh dev           # Start in development
  ./manage.sh logs api      # Show API logs
  ./manage.sh test          # Test endpoints

${YELLOW}Environment Variables:${NC}
  ENVIRONMENT    Set to 'development', 'staging', or 'production'
  DEBUG          Enable debug mode (true/false)
  LOG_LEVEL      Set logging level (DEBUG, INFO, WARNING, ERROR)

EOF
}

# Main script
main() {
    # Check prerequisites
    check_docker
    check_compose

    # Parse command
    COMMAND=${1:-help}
    shift || true

    case $COMMAND in
        build)
            cmd_build $@
            ;;
        up)
            cmd_up $@
            ;;
        dev)
            cmd_dev $@
            ;;
        down)
            cmd_down $@
            ;;
        restart)
            cmd_restart $@
            ;;
        stop)
            cmd_stop $@
            ;;
        start)
            cmd_start $@
            ;;
        logs)
            cmd_logs $@
            ;;
        shell)
            cmd_shell $@
            ;;
        status)
            cmd_status $@
            ;;
        test)
            cmd_test $@
            ;;
        clean)
            cmd_clean $@
            ;;
        help|--help|-h)
            cmd_help
            ;;
        *)
            print_error "Unknown command: $COMMAND"
            cmd_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"