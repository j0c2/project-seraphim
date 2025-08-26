#!/bin/bash
#
# Health Check Script for Project Seraphim
# Verifies all services are running and responding correctly
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
GATEWAY_URL="http://localhost:8000"
TORCHSERVE_INFERENCE_URL="http://localhost:8080"
TORCHSERVE_MGMT_URL="http://localhost:8081"
PROMETHEUS_URL="http://localhost:9090"
GRAFANA_URL="http://localhost:3000"

# Exit codes
EXIT_SUCCESS=0
EXIT_FAILURE=1

# Global status
OVERALL_STATUS=0

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    OVERALL_STATUS=1
}

check_service() {
    local service_name="$1"
    local url="$2"
    local timeout="${3:-5}"
    
    echo -n "Checking $service_name... "
    
    if curl -s --max-time "$timeout" "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        return 0
    else
        echo -e "${RED}✗${NC}"
        log_error "$service_name is not responding at $url"
        return 1
    fi
}

check_service_json() {
    local service_name="$1"
    local url="$2"
    local expected_field="$3"
    local timeout="${4:-5}"
    
    echo -n "Checking $service_name... "
    
    local response
    response=$(curl -s --max-time "$timeout" "$url" 2>/dev/null)
    local curl_exit_code=$?
    
    if [[ $curl_exit_code -ne 0 ]]; then
        echo -e "${RED}✗${NC}"
        log_error "$service_name is not responding at $url"
        return 1
    fi
    
    if [[ -n "$expected_field" ]]; then
        if echo "$response" | jq -e "$expected_field" > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC}"
            return 0
        else
            echo -e "${RED}✗${NC}"
            log_error "$service_name response missing expected field: $expected_field"
            return 1
        fi
    else
        echo -e "${GREEN}✓${NC}"
        return 0
    fi
}

check_docker_services() {
    echo "=== Docker Services ==="
    
    if ! command -v docker-compose &> /dev/null && ! command -v docker &> /dev/null; then
        log_error "Docker not found. Please install Docker."
        return 1
    fi
    
    # Check if docker-compose is running
    if docker-compose ps &> /dev/null; then
        local running_services
        running_services=$(docker-compose ps --services --filter "status=running")
        local all_services
        all_services=$(docker-compose ps --services)
        
        echo "Running services: $running_services"
        echo "Expected services: $all_services"
        
        if [[ "$running_services" != "$all_services" ]]; then
            log_warn "Not all services are running"
        else
            log_info "All Docker services are running"
        fi
    else
        log_warn "docker-compose not found in current directory"
    fi
    
    echo
}

check_endpoints() {
    echo "=== Service Endpoints ==="
    
    # Gateway health check
    check_service_json "Gateway Health" "$GATEWAY_URL/health" ".status" 10
    
    # TorchServe ping
    check_service "TorchServe Inference" "$TORCHSERVE_INFERENCE_URL/ping" 10
    
    # TorchServe management (list models)
    check_service_json "TorchServe Management" "$TORCHSERVE_MGMT_URL/models" ".models" 10
    
    # Prometheus
    check_service "Prometheus" "$PROMETHEUS_URL/-/healthy" 5
    
    # Grafana
    check_service_json "Grafana" "$GRAFANA_URL/api/health" ".database" 5
    
    echo
}

check_metrics() {
    echo "=== Metrics Collection ==="
    
    # Check if gateway metrics endpoint is responding
    echo -n "Checking Gateway metrics... "
    if curl -s --max-time 5 "$GATEWAY_URL/metrics" | grep -q "seraphim_"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        log_error "Gateway metrics not available or malformed"
    fi
    
    # Check if Prometheus is scraping targets
    echo -n "Checking Prometheus targets... "
    local targets_response
    targets_response=$(curl -s --max-time 5 "$PROMETHEUS_URL/api/v1/targets" 2>/dev/null)
    if echo "$targets_response" | jq -e '.data.activeTargets | length > 0' > /dev/null 2>&1; then
        local healthy_targets
        healthy_targets=$(echo "$targets_response" | jq '.data.activeTargets | map(select(.health == "up")) | length')
        local total_targets
        total_targets=$(echo "$targets_response" | jq '.data.activeTargets | length')
        echo -e "${GREEN}✓${NC} ($healthy_targets/$total_targets healthy)"
        
        if [[ "$healthy_targets" -lt "$total_targets" ]]; then
            log_warn "Some Prometheus targets are down"
        fi
    else
        echo -e "${RED}✗${NC}"
        log_error "No Prometheus targets found or targets unhealthy"
    fi
    
    echo
}

check_functionality() {
    echo "=== Functional Tests ==="
    
    # Test inference endpoint
    echo -n "Testing inference endpoint... "
    local inference_response
    inference_response=$(curl -s --max-time 10 -X POST "$GATEWAY_URL/api/v1/predict" \
        -H "Content-Type: application/json" \
        -d '{"model": "resnet18", "input": {"test": true}}' 2>/dev/null)
    local curl_exit_code=$?
    
    if [[ $curl_exit_code -eq 0 ]]; then
        # Check if we got a valid JSON response
        if echo "$inference_response" | jq . > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}?${NC}"
            log_warn "Inference endpoint returned non-JSON response"
        fi
    else
        echo -e "${RED}✗${NC}"
        log_error "Inference endpoint not responding"
    fi
    
    echo
}

check_resources() {
    echo "=== Resource Usage ==="
    
    if command -v docker &> /dev/null; then
        echo "Container resource usage:"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null || log_warn "Could not get container stats"
    fi
    
    echo
    echo "System resources:"
    echo "Disk usage: $(df -h . | tail -1 | awk '{print $5 " used (" $4 " free)"}')"
    
    if command -v free &> /dev/null; then
        echo "Memory usage: $(free -m | awk 'NR==2{printf "%.1f%% used (%s MB free)", $3*100/$2, $4 }')"
    elif command -v vm_stat &> /dev/null; then
        # macOS
        local page_size=$(vm_stat | grep "page size" | awk '{print $8}')
        local pages_free=$(vm_stat | grep "Pages free" | awk '{print $3}' | sed 's/\.//')
        local pages_active=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        local pages_inactive=$(vm_stat | grep "Pages inactive" | awk '{print $3}' | sed 's/\.//')
        local pages_wired=$(vm_stat | grep "Pages wired down" | awk '{print $4}' | sed 's/\.//')
        
        if [[ -n "$page_size" && -n "$pages_free" ]]; then
            local free_mb=$((pages_free * page_size / 1024 / 1024))
            local used_mb=$(((pages_active + pages_inactive + pages_wired) * page_size / 1024 / 1024))
            local total_mb=$((free_mb + used_mb))
            local used_percent=$((used_mb * 100 / total_mb))
            echo "Memory usage: ${used_percent}% used (${free_mb} MB free)"
        fi
    fi
    
    echo
}

print_summary() {
    echo "=== Health Check Summary ==="
    
    if [[ $OVERALL_STATUS -eq 0 ]]; then
        log_info "All systems operational ✨"
        echo
        echo "🚀 Platform is ready for inference requests"
        echo "📊 Monitoring: $GRAFANA_URL (admin/admin)"
        echo "📈 Metrics: $PROMETHEUS_URL"
        echo "🔍 API: $GATEWAY_URL"
    else
        log_error "Some issues detected ⚠️"
        echo
        echo "Please check the errors above and:"
        echo "1. Verify services are running: docker-compose ps"
        echo "2. Check service logs: docker-compose logs [service-name]"
        echo "3. Restart if needed: docker-compose restart [service-name]"
    fi
    
    echo
}

# Main execution
main() {
    echo "🛡️  Project Seraphim Health Check"
    echo "=================================="
    echo
    
    check_docker_services
    check_endpoints
    check_metrics
    check_functionality
    check_resources
    print_summary
    
    exit $OVERALL_STATUS
}

# Check if script is being sourced or executed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
