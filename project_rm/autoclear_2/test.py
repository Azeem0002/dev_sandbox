"""
tests/test_autoclear.py
Simple smoke tests for autoclear robot.
"""

import pytest
import subprocess
from tenacity import RetryError
from unittest.mock import patch, MagicMock

from autoclear import (
    AutoclearConfig,
    _get_clear_command,
    _execute_command,
    with_retry,
    clear_terminal,
    run_autoclear
)


# ============================================================================
# PATTERN 1: PURE FUNCTION TESTS
# ============================================================================
# Pattern: Test functions with no external dependencies
# Method: Call function with inputs, assert outputs match
# ============================================================================

class TestResponsibilities:
    """Tests for low-level building blocks."""
    
    def test_get_clear_command_windows(self):
        # PATTERN: Patch external dependency (os.name) to control environment
        # WHY: We need to test Windows behavior without being on Windows
        """Test get clear command windows."""
        with patch('autoclear.os.name', 'nt'): # make real function fake function
            # Call function with patched dependency
            result = _get_clear_command()
            # Assert output matches expected. if func returns a value, use assert func == return_value
            assert result == ["cmd", "/c", "cls"]
    
    def test_get_clear_command_unix(self):
        # PATTERN: Same test, different patch value
        """Test get clear command unix."""
        with patch('autoclear.os.name', 'posix'):
            assert _get_clear_command() == ["clear"]
    
    def test_execute_command_success(self):
        # PATTERN: Mock external call to avoid real system execution
        # WHY: We don't want to actually run system commands during tests
        """Test execute command success."""
        with patch('autoclear.subprocess.run') as mock_run:
            # Call function that uses the mocked dependency
            _execute_command(["echo", "hi"])
            # PATTERN: Verify mock was called with correct arguments
            # WHY: Asserting behavior, not just result (function returns None)
            mock_run.assert_called_once_with(["echo", "hi"], timeout=5, check=True)
            # assert_called_once_with: used for actions/behaviors

    def test_execute_command_failure(self):
        # PATTERN: Mock error condition
        # WHY: Test error handling without actually causing errors
        """Test execute command failure."""
        with patch('autoclear.subprocess.run', side_effect=subprocess.CalledProcessError(1, "cmd")):
            # PATTERN: Assert exception is raised
            # WHY: Verify function properly propagates errors
            with pytest.raises(RuntimeError, match=r"Clear failed: \['bad'\]"):
                _execute_command(["bad"])
            # match: verifies the lines error message


# ============================================================================
# PATTERN 2: DECORATOR/FEATURE TESTS
# ============================================================================
# Pattern: Test wrapper functions that add behavior
# Method: Create mock function, apply decorator, verify wrapper adds behavior
# ============================================================================

class TestFeatures:
    """Tests for reusable behaviors."""
    
    def test_with_retry_succeeds_first_try(self):
        # PATTERN: Create mock to record calls
        # WHY: We need to verify retry behavior without complex setup
        """Test with retry succeeds first try."""
        mock_func = MagicMock(return_value="ok")
        # MagicMock: a fake func that always returns 'ok'
        
        # Apply the feature (retry decorator)
        decorated = with_retry(3, 0.01)(mock_func)
        
        # Call the decorated function
        result = decorated()
        
        # PATTERN: Verify result AND mock was called exactly once
        # WHY: First try succeeded, so no retries happened
        assert result == "ok" # necessary to verify functions that always returns results
        mock_func.assert_called_once() # Test behavior
    
    def test_with_retry_eventual_success(self):
        # PATTERN: Mock with side_effect to simulate failures then success
        # WHY: Test retry logic: fail, fail, succeed
        """Test with retry eventual success."""
        mock_func = MagicMock(side_effect=[Exception("fail"), "ok"]) 
        # MagicMock(side_effect=[Exception("fail"), "ok"]) : fails first then succeed
        
        decorated = with_retry(3, 0.01)(mock_func)
        
        # Call should succeed after retries
        result = decorated()
        
        assert result == "ok"
        # PATTERN: Verify number of attempts (2 failures + 1 success = 3 attempts)
        # WHY: Confirms retry happened when needed
        assert mock_func.call_count == 2
    
    def test_with_retry_fails_after_max(self):
        # PATTERN: Mock that always fails
        """Test with retry fails after max."""
        mock_func = MagicMock(side_effect=RuntimeError("fail"))
        
        decorated = with_retry(2, 0.01)(mock_func)
        
        # PATTERN: Assert exception is raised after exhausting retries
        # WHY: Verify it doesn't retry forever
        with pytest.raises(RuntimeError, match="fail"):
            decorated()
        
        # PATTERN: Verify exact number of attempts (max_retries)
        assert mock_func.call_count == 2


# ============================================================================
# PATTERN 3: ORCHESTRATION TESTS
# ============================================================================
# Pattern: Test that public function coordinates dependencies correctly
# Method: Mock ALL dependencies, verify they're called with correct args/order
# ============================================================================

class TestClearTerminal:
    """Tests for single clear operation."""
    
    def test_calls_execute_command(self):
        # PATTERN: Mock ALL dependencies of the orchestration function
        # WHY: Isolate orchestration logic from implementation
        """Test calls execute command."""
        config = AutoclearConfig(max_retries=1, retry_delay=0.01)
        
        with patch('autoclear._get_clear_command', return_value=["test"]), \
             patch('autoclear._execute_command') as mock_exec:
            
            # Call the orchestrator
            clear_terminal(config)
            
            # PATTERN: Verify the correct function was called with correct args
            # WHY: Orchestration should wire dependencies correctly
            mock_exec.assert_called_once_with(["test"])
            # assert_called_once_with(["arguments"]) is used for arguments once
            
    def test_retries_on_failure(self):
        # PATTERN: Test failure handling in orchestration
        """Test retries on failure."""
        config = AutoclearConfig(max_retries=3, retry_delay=0.01)
        
        with patch('autoclear._get_clear_command', return_value=["clear"]), \
            patch('autoclear._execute_command') as mock_exec:
            
            # PATTERN: Simulate failures then success
            # WHY: Verify retry logic works at orchestration level
            mock_exec.side_effect = [Exception("fail1"), Exception("fail2"), None]
            
            clear_terminal(config)
            
            # PATTERN: Verify retry attempts count
            assert mock_exec.call_count == 3


# ============================================================================
# PATTERN 4: INFINITE LOOP TESTS
# ============================================================================
# Pattern: Test loops that run forever
# Method: Force exit via exception, verify loop body executed correctly
# ============================================================================

class TestRunAutoclear:
    """Tests for robot loop."""
    
    def test_calls_clear_and_sleep(self):
        # PATTERN: Test infinite loop by raising exception to break out
        # WHY: Can't let loop run forever in tests
        """Test calls clear and sleep."""
        config = AutoclearConfig(interval=1)
        
        with patch('autoclear.clear_terminal') as mock_clear, \
            patch('autoclear._sleep', side_effect=KeyboardInterrupt) as mock_sleep:
            
            # PATTERN: Expect the exception that breaks the loop
            # WHY: KeyboardInterrupt is how we signal test to stop
            with pytest.raises(KeyboardInterrupt):
                run_autoclear(config)
            
            # PATTERN: Verify loop executed at least once
            # WHY: Confirms loop body ran before interruption
            mock_clear.assert_called_once_with(config)
            mock_sleep.assert_called_once_with(1)


# ============================================================================
# PATTERN 5: DATA MODEL TESTS
# ============================================================================
# Pattern: Test configuration/dataclass behavior
# Method: Create instances, verify values and constraints
# ============================================================================

class TestAutoclearConfig:
    """Tests for configuration."""
    
    def test_defaults(self):
        # PATTERN: Test default values
        # WHY: Verify sensible defaults are set
        """Test defaults."""
        cfg = AutoclearConfig()
        assert cfg.interval == 600
        assert cfg.max_retries == 3
        assert cfg.retry_delay == 1.0
    
    def test_custom_values(self):
        # PATTERN: Test custom values override defaults
        # WHY: Verify configuration can be customized
        """Test custom values."""
        cfg = AutoclearConfig(interval=5, max_retries=4, retry_delay=0.5)
        assert cfg.interval == 5
        assert cfg.max_retries == 4
        assert cfg.retry_delay == 0.5
    
    def test_immutable(self):
        # PATTERN: Test data integrity constraints
        # WHY: Verify frozen dataclass prevents accidental modification
        """Test immutable."""
        cfg = AutoclearConfig()
        with pytest.raises(Exception):
            cfg.interval = 10  # type: ignore