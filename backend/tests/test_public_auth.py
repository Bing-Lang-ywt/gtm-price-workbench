"""Unconfigured credentials must not become a shared login."""
from app.core import security


def test_empty_development_password_disables_login(monkeypatch):
    monkeypatch.setattr(security, 'DEV_EMAIL', 'analyst@example.com')
    monkeypatch.setattr(security, 'DEV_PASSWORD', '')
    monkeypatch.setattr(security, 'MARKET_ACCOUNTS', {})
    assert security.authenticate('analyst@example.com', '') is None
    assert security.authenticate('analyst@example.com', '__unset__') is None
