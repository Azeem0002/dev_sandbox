"""Small lifecycle/status models shared by autoclear boundary and application code.
lifecycle_models.py is for models that describe runtime state/lifecycle.
no AutoclearStart and AutoclearS stop Because start/stop are actions, not state snapshots.
"""
# Models are structured container for information describing a state
# create a model when multiple piece of data belongs/travel together

from dataclasses import dataclass
from pathlib import Path

# Dataclass = Blueprint (can create ANY AutoclearStatus)
# Dataclass = A toy mold that can make any toy

@dataclass(frozen=True)
class AutoclearStatus:
    """Application-facing snapshot of the autoclear backend state."""
    backend: str  # Currently running as a native OS background process. not systemd or docker
    is_running: bool
    pid: int | None
    interval_seconds: int | None
    last_trigger: str | None
    detail: str | None
    pid_file: Path | None = None
    target_tty: str | None = None

# ==========================
# CONFIGURATIONS
# ==========================
@dataclass(frozen=True) # frozen makes configuration immutable when calling config
class AutoclearConfig:
    interval: int = 3600 # 1h
    max_retries: int = 3
    retry_delay: float = 1.0
