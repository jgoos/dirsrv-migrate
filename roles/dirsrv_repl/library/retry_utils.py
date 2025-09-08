#!/usr/bin/env python3
"""
Retry utilities for 389-DS replication operations.
Provides adaptive retry logic with exponential backoff and circuit breaker patterns.
"""

import time
import random
from typing import Callable, Any, Optional, Dict, List
from ansible.module_utils.basic import AnsibleModule


class RetryConfig:
    """Configuration for retry operations."""
    
    def __init__(self, max_retries: int = 30, base_delay: float = 2.0, 
                 max_delay: float = 60.0, backoff_multiplier: float = 1.5,
                 jitter: bool = True, circuit_breaker_threshold: int = 5):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.jitter = jitter
        self.circuit_breaker_threshold = circuit_breaker_threshold


class CircuitBreaker:
    """Circuit breaker pattern for failing operations."""
    
    def __init__(self, threshold: int = 5, timeout: float = 60.0):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def can_execute(self) -> bool:
        """Check if operation can be executed based on circuit breaker state."""
        now = time.time()
        
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            if now - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def record_success(self):
        """Record successful operation."""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.threshold:
            self.state = "OPEN"


class AdaptiveRetry:
    """Adaptive retry mechanism with exponential backoff and circuit breaker."""
    
    def __init__(self, config: RetryConfig):
        self.config = config
        self.circuit_breaker = CircuitBreaker(config.circuit_breaker_threshold)
        self.retry_count = 0
        self.last_delay = config.base_delay
    
    def calculate_delay(self) -> float:
        """Calculate next delay with exponential backoff and jitter."""
        if self.retry_count == 0:
            delay = self.config.base_delay
        else:
            delay = min(
                self.last_delay * self.config.backoff_multiplier,
                self.config.max_delay
            )
        
        if self.config.jitter:
            # Add jitter to prevent thundering herd
            jitter_factor = random.uniform(0.5, 1.5)
            delay *= jitter_factor
        
        self.last_delay = delay
        return delay
    
    def should_retry(self, exception: Exception) -> bool:
        """Determine if operation should be retried based on exception type."""
        # Retry on transient errors
        retryable_errors = [
            "timeout", "connection", "network", "temporary", "busy",
            "locked", "resource", "unavailable", "can't contact",
            "unknown", "in progress", "update in progress"
        ]
        
        error_msg = str(exception).lower()
        return any(keyword in error_msg for keyword in retryable_errors)
    
    def execute_with_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """Execute operation with adaptive retry logic."""
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            if not self.circuit_breaker.can_execute():
                raise Exception(f"Circuit breaker is OPEN after {self.failure_count} failures")
            
            try:
                result = operation(*args, **kwargs)
                self.circuit_breaker.record_success()
                self.retry_count = 0
                return result
                
            except Exception as e:
                last_exception = e
                self.circuit_breaker.record_failure()
                
                if not self.should_retry(e) or attempt == self.config.max_retries:
                    break
                
                delay = self.calculate_delay()
                time.sleep(delay)
                self.retry_count += 1
        
        raise last_exception


def retry_operation(operation: Callable, config: RetryConfig, *args, **kwargs) -> Any:
    """Convenience function for retrying operations."""
    retry = AdaptiveRetry(config)
    return retry.execute_with_retry(operation, *args, **kwargs)


def create_retry_config_from_ansible(module: AnsibleModule) -> RetryConfig:
    """Create RetryConfig from Ansible module parameters."""
    retry_settings = module.params.get('retry_settings', {})
    
    return RetryConfig(
        max_retries=retry_settings.get('max_retries', 30),
        base_delay=retry_settings.get('base_delay', 2.0),
        max_delay=retry_settings.get('max_delay', 60.0),
        backoff_multiplier=retry_settings.get('backoff_multiplier', 1.5),
        jitter=retry_settings.get('jitter', True),
        circuit_breaker_threshold=retry_settings.get('circuit_breaker_threshold', 5)
    )


class ReplicationHealthChecker:
    """Comprehensive health checker for replication operations."""
    
    def __init__(self, module: AnsibleModule):
        self.module = module
    
    def check_ldapi_connectivity(self) -> bool:
        """Check LDAPI socket connectivity."""
        try:
            result = self.module.run_command([
                'ldapsearch', '-Y', 'EXTERNAL', '-H', 
                self.module.params.get('ldapi_uri', 'ldapi://%2Fdata%2Frun%2Fslapd-localhost.socket'),
                '-s', 'base', '-b', '', '1.1'
            ])
            return result[0] == 0
        except Exception:
            return False
    
    def check_remote_ldap_connectivity(self, host: str, port: int) -> bool:
        """Check remote LDAP server connectivity."""
        try:
            result = self.module.run_command([
                'ldapsearch', '-x', '-H', f'ldap://{host}:{port}',
                '-s', 'base', '-b', '', '1.1'
            ])
            return result[0] == 0
        except Exception:
            return False
    
    def check_replication_enabled(self, suffix: str) -> bool:
        """Check if replication is enabled for a suffix."""
        try:
            result = self.module.run_command([
                'dsconf', '-D', 'cn=Directory Manager', '-w', 
                self.module.params.get('password', 'password'),
                'ldap://localhost:3389', 'replication', 'get', '--suffix', suffix
            ])
            return result[0] == 0 and 'enabled' in result[1].lower()
        except Exception:
            return False
    
    def check_agreement_status(self, suffix: str, agreement_name: str) -> Dict[str, Any]:
        """Check replication agreement status."""
        try:
            result = self.module.run_command([
                'dsconf', '-D', 'cn=Directory Manager', '-w',
                self.module.params.get('password', 'password'),
                'ldap://localhost:3389', 'repl-agmt', 'init-status',
                '--suffix', suffix, agreement_name
            ])
            
            status = {
                'rc': result[0],
                'stdout': result[1],
                'stderr': result[2],
                'is_healthy': result[0] == 0 and 'successfully initialized' in result[1].lower()
            }
            return status
        except Exception as e:
            return {
                'rc': -1,
                'stdout': '',
                'stderr': str(e),
                'is_healthy': False
            }
