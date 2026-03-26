import pytest
import subprocess
from unittest.mock import patch, MagicMock
from autoclear import (
    AutoclearConfig,
    _get_clear_command,
    _execute_command,
    with_retry,
    clear_terminal,
    run_autoclear
)

# -----------------------------
# RESPONSIBILITY TESTS
# -----------------------------
class TestResponsibilities:

    def test_get_clear_command_windows(self):
        with patch('autoclear.os.name', 'nt'):
            assert _get_clear_command() == ["cmd", "/c", "cls"]

    def test_get_clear_command_unix(self):
        with patch('autoclear.os.name', 'posix'):
            assert _get_clear_command() == ["clear"]

    def test_execute_command_success(self):
        with patch('subprocess.run') as mock_run:
            _execute_command(["echo", "hi"])
            mock_run.assert_called_once_with(["echo", "hi"], check=True)

    def test_execute_command_failure(self):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, "cmd")):
            with pytest.raises(subprocess.CalledProcessError):
                _execute_command(["bad"])


# -----------------------------
# FEATURE TESTS
# -----------------------------
class TestFeatures:

    def test_with_retry_succeeds_first_try(self):
        mock_func = MagicMock(return_value="ok")
        decorated = with_retry(3, 0.01)(mock_func)
        assert decorated() == "ok"
        mock_func.assert_called_once()

    def test_with_retry_eventual_success(self):
        mock_func = MagicMock(side_effect=[Exception("fail"), "ok"])
        decorated = with_retry(3, 0.01)(mock_func)
        assert decorated() == "ok"
        assert mock_func.call_count == 2

    def test_with_retry_fails_after_max(self):
        mock_func = MagicMock(side_effect=Exception("fail"))
        decorated = with_retry(2, 0.01)(mock_func)
        with pytest.raises(Exception, match="fail"):
            decorated()
        assert mock_func.call_count == 2


# -----------------------------
# PUBLIC FUNCTION TESTS
# -----------------------------
class TestPublicFunctions:

    def test_clear_terminal_calls_execute_command(self):
        config = AutoclearConfig(max_retries=1, retry_delay=0.01)
        with patch('autoclear._get_clear_command', return_value=["test"]), \
             patch('autoclear._execute_command') as mock_exec:
            clear_terminal(config)
            mock_exec.assert_called_once_with(["test"])

    def test_clear_terminal_retries_on_failure(self):
        config = AutoclearConfig(max_retries=3, retry_delay=0.01)
        with patch('autoclear._get_clear_command', return_value=["clear"]), \
             patch('autoclear._execute_command') as mock_exec:
            mock_exec.side_effect = [Exception("fail1"), Exception("fail2"), None]
            clear_terminal(config)
            assert mock_exec.call_count == 3


# -----------------------------
# WORKER LOOP TESTS
# -----------------------------
class TestWorkerLoop:

    def test_run_autoclear_calls_clear_and_sleep(self):
        config = AutoclearConfig(interval=1)
        with patch('autoclear.clear_terminal') as mock_clear, \
             patch('autoclear._sleep') as mock_sleep:
            mock_sleep.side_effect = [None, StopIteration]
            with pytest.raises(StopIteration):
                run_autoclear(config)
            assert mock_clear.call_count == 2
            assert mock_sleep.call_count == 2

    def test_run_autoclear_continues_on_clear_error(self):
        config = AutoclearConfig(interval=1)
        with patch('autoclear.clear_terminal') as mock_clear, \
             patch('autoclear._sleep') as mock_sleep:
            mock_clear.side_effect = [Exception("fail"), None, StopIteration]
            mock_sleep.side_effect = [None, None, StopIteration]
            with pytest.raises(StopIteration):
                run_autoclear(config)
            assert mock_clear.call_count == 2


# -----------------------------
# CONFIGURATION TESTS
# -----------------------------
class TestAutoclearConfig:

    def test_autoclear_config_defaults(self):
        cfg = AutoclearConfig()
        assert cfg.interval == 600
        assert cfg.max_retries == 3
        assert cfg.retry_delay == 1.0

    def test_autoclear_config_custom_values(self):
        cfg = AutoclearConfig(interval=5, max_retries=4, retry_delay=0.5)
        assert cfg.interval == 5
        assert cfg.max_retries == 4
        assert cfg.retry_delay == 0.5

    def test_autoclear_config_immutable(self):
        cfg = AutoclearConfig()
        with pytest.raises(Exception):
            cfg.interval = 10  # type: ignore