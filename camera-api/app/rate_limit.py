from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

_limiter_kwargs: dict = {"key_func": get_remote_address}
_redis = (settings.redis_url or "").strip()
if _redis:
    _limiter_kwargs["storage_uri"] = _redis

# IP-based limiter — in-memory when REDIS_URL is unset; shared across workers when set.
limiter = Limiter(**_limiter_kwargs)
