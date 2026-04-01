
#Controller.py

# User story
user needs a controller for autoclear terminal. controller should be able to start, stop, check status and restart the autoclear robot in the background.

# Capabilities
- Check if robot is running (status)
- Stop running robot gracefully
- Start robot in background with custom interval
- Restart robot (stop then start)

# Public functions
autoclear_status()
autoclear_stop()
autoclear_start()
autoclear_restart()


# functions for autoclear_status() first
autoclear_status()
    _get_pid_file_path()
    _read_pid()
    _is_process_running()
        _is_our_process()


# Features
with_timeout()
with pid_lock()

# Orchestration (state)
cli


