#!/bin/bash
# Fail Fast Test Wrapper
# Usage: ./test_fail_fast.sh <test_command> <timeout_seconds>

set -euo pipefail

TEST_COMMAND="$1"
TIMEOUT_SECONDS="${2:-300}"  # Default 5 minutes
LOG_FILE="test_output_$(date +%Y%m%d_%H%M%S).log"

echo "🚀 Starting test with ${TIMEOUT_SECONDS}s timeout..."
echo "📝 Logging to: $LOG_FILE"
echo "⏰ Command: $TEST_COMMAND"
echo "----------------------------------------"

# Function to cleanup on exit
cleanup() {
    echo "🧹 Cleaning up..."
    pkill -f "ansible-playbook.*repl_mesh" 2>/dev/null || true
    pkill -f "ansible-playbook.*repl" 2>/dev/null || true
}

trap cleanup EXIT

# Function to analyze failure
analyze_failure() {
    local exit_code=$1
    echo "❌ Test failed or timed out (exit code: $exit_code)"
    
    if [ $exit_code -eq 124 ]; then
        echo "⏰ Test timed out after ${TIMEOUT_SECONDS} seconds"
    fi
    
    echo "📊 Analyzing failure..."
    
    # Check for common failure patterns
    echo "🔍 Checking for common issues:"
    
    if grep -q "failed=1" "$LOG_FILE"; then
        echo "❌ Found failed tasks:"
        grep -A5 -B5 "failed=1" "$LOG_FILE" | tail -20
    fi
    
    if grep -q "RUV error\|generation ID" "$LOG_FILE"; then
        echo "❌ Found RUV/generation ID errors:"
        grep -A3 -B3 "RUV error\|generation ID" "$LOG_FILE"
    fi
    
    if grep -q "Error (19)\|Error (12)" "$LOG_FILE"; then
        echo "❌ Found replication errors:"
        grep -A3 -B3 "Error (19)\|Error (12)" "$LOG_FILE"
    fi
    
    if grep -q "timeout\|Timeout" "$LOG_FILE"; then
        echo "⏰ Found timeout issues:"
        grep -A3 -B3 "timeout\|Timeout" "$LOG_FILE"
    fi
    
    echo "📋 Last 20 lines of output:"
    tail -20 "$LOG_FILE"
    
    echo "💾 Full log saved to: $LOG_FILE"
    exit 1
}

# Run the test with timeout
if command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout"
elif command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout"
else
    # Fallback: run in background and kill after timeout
    echo "⚠️  No timeout command found, using background process method"
    bash -c "$TEST_COMMAND" > "$LOG_FILE" 2>&1 &
    TEST_PID=$!
    
    # Wait for timeout or completion
    for i in $(seq 1 "$TIMEOUT_SECONDS"); do
        if ! kill -0 "$TEST_PID" 2>/dev/null; then
            wait "$TEST_PID"
            EXIT_CODE=$?
            break
        fi
        sleep 1
    done
    
    # If still running, kill it
    if kill -0 "$TEST_PID" 2>/dev/null; then
        echo "⏰ Killing test after ${TIMEOUT_SECONDS} seconds"
        kill -TERM "$TEST_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$TEST_PID" 2>/dev/null || true
        EXIT_CODE=124
    fi
    
    # Show the log
    cat "$LOG_FILE"
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "✅ Test completed successfully!"
        exit 0
    else
        analyze_failure $EXIT_CODE
    fi
fi

# Use timeout command if available
if $TIMEOUT_CMD "$TIMEOUT_SECONDS" bash -c "$TEST_COMMAND" 2>&1 | tee "$LOG_FILE"; then
    echo "✅ Test completed successfully!"
    exit 0
else
    analyze_failure $?
fi