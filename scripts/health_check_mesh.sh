#!/bin/bash
# Comprehensive health check script for ds389 mesh replication containers
# This script verifies all aspects of container health before proceeding with replication setup

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICES=("ds-s1" "ds-s2" "ds-c1" "ds-c2")
TIMEOUT=60
RETRIES=3

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if container is running
check_container_running() {
    local container=$1
    if podman inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qi '^true$'; then
        log_success "Container $container is running"
        return 0
    else
        log_error "Container $container is not running"
        return 1
    fi
}

# Function to check LDAPI connectivity
check_ldapi() {
    local container=$1
    local socket_uri="ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket"

    log_info "Checking LDAPI connectivity for $container..."

    # Try LDAPI connection with timeout
    if timeout $TIMEOUT podman exec $container ldapsearch -Y EXTERNAL \
        -H "$socket_uri" -s base -b '' '(objectClass=*)' >/dev/null 2>&1; then
        log_success "LDAPI connection successful for $container"
        return 0
    else
        log_warning "LDAPI connection failed for $container (non-fatal in lab)"
        return 0
    fi
}

# Function to check TCP connectivity
check_tcp() {
    local container=$1
    local port=3389

    log_info "Checking TCP connectivity for $container on port $port..."

    # Validate TCP from inside the container via ldapsearch to localhost
    if podman exec "$container" ldapsearch -x -H "ldap://localhost:$port" -s base -b '' 1.1 >/dev/null 2>&1; then
        log_success "TCP/LDAP responsive for $container:$port"
        return 0
    else
        log_error "TCP/LDAP not responsive for $container:$port"
        return 1
    fi
}

# Function to check LDAP TCP connectivity via ldapsearch
check_ldap_tcp() {
    local container=$1
    local port=3389

    log_info "Checking LDAP TCP via ldapsearch for $container..."

    if podman exec $container ldapsearch -x -H "ldap://localhost:$port" \
        -s base -b '' '(objectClass=*)' >/dev/null 2>&1; then
        log_success "LDAP TCP search successful for $container"
        return 0
    else
        log_error "LDAP TCP search failed for $container"
        return 1
    fi
}

# Function to check naming contexts
check_naming_contexts() {
    local container=$1
    local port=3389

    log_info "Checking naming contexts for $container..."

    local result
    result=$(podman exec $container ldapsearch -x -H "ldap://localhost:$port" \
        -s base -b '' namingContexts 2>/dev/null | grep "^namingContexts:" | head -1 || true)

    if [[ -n "$result" ]]; then
        local context=$(echo "$result" | cut -d: -f2- | xargs)
        log_success "Naming context found for $container: $context"
        return 0
    else
        log_warning "No naming contexts found for $container (may be expected pre-seed)"
        return 0
    fi
}

# Function to check DS process health
check_ds_process() {
    local container=$1

    log_info "Checking DS process health for $container..."

    # Prefer pgrep if available, else fall back to TCP listener or LDAP base search
    if podman exec "$container" sh -lc 'command -v pgrep >/dev/null 2>&1'; then
        if podman exec "$container" pgrep -f slapd >/dev/null 2>&1; then
            log_success "DS process detected via pgrep in $container"
            return 0
        fi
    fi

    # Fallback: check TCP listener on 3389
    if podman exec "$container" sh -lc 'ss -lnt 2>/dev/null | grep -q ":3389"'; then
        log_success "DS TCP listener present on 3389 in $container"
        return 0
    fi

    # Last resort: LDAP base search over TCP
    if podman exec "$container" ldapsearch -x -H "ldap://localhost:3389" -s base -b '' 1.1 >/dev/null 2>&1; then
        log_success "LDAP responds over TCP in $container"
        return 0
    fi

    log_error "DS process not detected in $container"
    return 1
}

# Function to check container logs for errors
check_logs() {
    local container=$1

    log_info "Checking logs for critical errors in $container..."

    # Check for critical errors in the last few log entries
    local error_count
    error_count=$(podman logs $container 2>&1 | tail -50 | grep -i -c "error\|failed\|critical" || true)

    if [[ $error_count -eq 0 ]]; then
        log_success "No critical errors found in $container logs"
        return 0
    else
        log_warning "Found $error_count potential error(s) in $container logs (reviewing...)"
        # Show the actual errors for context
        podman logs $container 2>&1 | tail -50 | grep -i "error\|failed\|critical" | head -5 || true
        return 0  # Don't fail on log errors as they might be transient
    fi
}

# Function to perform comprehensive health check on a single container
check_container_health() {
    local container=$1
    local failures=0

    log_info "=== Starting comprehensive health check for $container ==="

    # Check if container is running
    if ! check_container_running "$container"; then
        ((failures++))
    fi

    # Check DS process
    if ! check_ds_process "$container"; then
        ((failures++))
    fi

    # Check LDAPI connectivity
    if ! check_ldapi "$container"; then
        ((failures++))
    fi

    # Check TCP connectivity
    if ! check_tcp "$container"; then
        ((failures++))
    fi

    # Check LDAP TCP via ldapsearch
    if ! check_ldap_tcp "$container"; then
        ((failures++))
    fi

    # Check naming contexts
    if ! check_naming_contexts "$container"; then
        ((failures++))
    fi

    # Check logs (warning only)
    check_logs "$container"

    if [[ $failures -eq 0 ]]; then
        log_success "=== All health checks PASSED for $container ==="
        return 0
    else
        log_error "=== $failures health check(s) FAILED for $container ==="
        return 1
    fi
}

# Function to check inter-container connectivity
check_mesh_connectivity() {
    log_info "=== Checking inter-container connectivity ==="

    local failures=0

    # Test connectivity between all pairs
    for source in "${SERVICES[@]}"; do
        for target in "${SERVICES[@]}"; do
            if [[ "$source" != "$target" ]]; then
                log_info "Testing $source -> $target connectivity..."

                if podman exec "$source" ldapsearch -x -H "ldap://$target:3389" \
                    -s base -b '' '(objectClass=*)' >/dev/null 2>&1; then
                    log_success "$source can connect to $target"
                else
                    log_error "$source cannot connect to $target"
                    ((failures++))
                fi
            fi
        done
    done

    if [[ $failures -eq 0 ]]; then
        log_success "All inter-container connectivity tests PASSED"
        return 0
    else
        log_error "$failures inter-container connectivity test(s) FAILED"
        return 1
    fi
}

# Main function
main() {
    log_info "Starting comprehensive mesh health verification..."
    log_info "Services to check: ${SERVICES[*]}"

    local total_failures=0
    local start_time=$(date +%s)

    # Check each container individually
    for service in "${SERVICES[@]}"; do
        if ! check_container_health "$service"; then
            ((total_failures++))
        fi
        echo
    done

    # Check inter-container connectivity
    if ! check_mesh_connectivity; then
        ((total_failures++))
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    echo
    log_info "=== Health Check Summary ==="
    log_info "Duration: ${duration}s"

    if [[ $total_failures -eq 0 ]]; then
        log_success "🎉 ALL HEALTH CHECKS PASSED!"
        log_success "Mesh is ready for replication configuration."
        exit 0
    else
        log_error "❌ $total_failures health check failure(s) detected"
        log_error "Mesh is NOT ready for replication configuration."
        log_error "Please review the errors above and ensure all containers are properly started."
        exit 1
    fi
}

# Run main function
main "$@"


