import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Disable rate limiting in test environment to avoid fixture interference
_enabled = os.environ.get("APP_ENV", "development") != "testing"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=_enabled,
)
