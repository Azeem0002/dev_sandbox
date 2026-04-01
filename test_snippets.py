import pytest
import subprocess
from unittest.mock import patch, MagicMock

from .main import(
    AutoclearConfig,
    _get_clear_command,
    _execute_command,
    clear_terminal,
    run_autoclear,
    with_retry
)

class TestUnit:
    
    def test_get_clear_command_windows(self):
        with patch('main.os.name', 'nt'):
            result = _get_clear_command
            assert result == ["cmd", "/c", "cls"] 
    
    def test_get_clear_command_unix(self):
        with patch('main.os.name' , 'posix'):
            result = _get_clear_command
            assert result == ["clear"]
    
    def test_execute_command(self):
        with patch('main.subprocess.run') as mock_run:
            _execute_command(["clear"])
            mock_run.assert_called_once_with(["clear"], timeout=5, check=True)
        
        with patch('main.subprocess.run', side_effect=subprocess.CalledProcessError(1, "cmd")):
            with pytest.raises(RuntimeError, match=r"clear failed: \['bad'\]"):
                _execute_command(['bad'])
    

class IntegrationTest:

    def test_with_retry(self):
        mock_func= MagicMock(return_value='ok')
        decorated =  with_retry(3, 0.01)(mock_func)
        result = decorated()

        assert result == 1
        mock_func.assert_called_once()

        mock_func = MagicMock(side_effect=[Exception('fail'), 'ok'])
        decorated = with_retry(3, 0.01)(mock_func)
        result = decorated()

        assert result == 1
        assert mock_func.call_count == 2

        mock_func=MagicMock(side_effect=RuntimeError('fail'))
        decorated = with_retry(2, 0.01)(mock_func)
        with pytest.raises(RuntimeError, match='fail'):
            decorated()
        assert mock_func.call_count == 2

class TestOrchestration:

    def test_call_execution_command(self):

        config = AutoclearConfig(max_retries=1, retry_delay=0.01)

        with patch('main.get_clear_command', return_value=['test']), \
             patch('main.execute_command') as mock_exec:
            
            clear_terminal(config)
            mock_exec.assert_called_once_with(["test"])

    def test_config(self):
        cfg =AutoclearConfig()
        assert cfg.interval == 600
        assert cfg.max_retries == 3
        assert cfg.retry_delay == 1.0

