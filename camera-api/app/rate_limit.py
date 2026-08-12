from slowapi import Limiter
from slowapi.util import get_remote_address

# IP-based, in-memory limiter — good enough for a single-instance deployment.
# Multi-instance deployments should point slowapi at Redis instead
# (Limiter(storage_uri="redis://...")) so limits are shared across workers.
limiter = Limiter(key_func=get_remote_address)
