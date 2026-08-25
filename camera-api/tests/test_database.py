from app.config import settings
from app.database import engine


def test_engine_pool_size_matches_settings():
    assert engine.pool.size() == settings.db_pool_size


def test_engine_pool_pre_ping_is_enabled():
    # Recycles dead connections automatically instead of surfacing a
    # stale-connection error to whichever AI sweep loop happened to grab
    # one after a DB restart/network blip.
    assert engine.pool._pre_ping is True


def test_engine_overflow_matches_settings():
    assert engine.pool._max_overflow == settings.db_max_overflow
