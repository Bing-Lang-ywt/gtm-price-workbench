import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_session
from app.core.security import create_token
from app.services.price_preflight import preflight_price


@pytest.mark.parametrize('price,code', [
    (float('nan'), 'not_finite'), (float('inf'), 'not_finite'),
    (-float('inf'), 'not_finite'), (10**400, 'not_finite'),
    (-1, 'not_positive'), (0, 'not_positive'),
    (True, 'not_numeric'), ('12.5', 'not_numeric'),
    (None, 'not_numeric'), ({}, 'not_numeric'),
])
def test_invalid_amount_has_safe_reason(price, code):
    assert preflight_price(price, 'unlocked', 'EUR') == {
        'valid': False, 'issues': [{'field': 'price', 'code': code,
                                  'message': {'not_finite': 'Price must be finite.',
                                              'not_positive': 'Preview requires a price greater than zero.',
                                              'not_numeric': 'Price must be a number, not a boolean or numeric string.'}[code]}]}


@pytest.mark.parametrize('price_type', ['unlocked', 'contract_monthly', 'subsidy_down_payment'])
@pytest.mark.parametrize('currency', ['EUR', 'RSD', 'HUF', 'RON', 'BGN', 'PLN', 'CZK'])
def test_supported_types_and_currencies(price_type, currency):
    assert preflight_price(12.5, price_type, currency) == {'valid': True, 'issues': []}


def test_multiple_issues_and_strict_codes():
    result = preflight_price(-1, 'unknown', 'eur')
    assert [issue['code'] for issue in result['issues']] == [
        'not_positive', 'unsupported_price_type', 'unsupported_currency']
    assert preflight_price(1, [], {})['valid'] is False


def test_api_auth_validation_and_no_database_dependency():
    def forbidden_session():
        raise AssertionError('Preflight must not request a database session')
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = forbidden_session
    try:
        client = TestClient(app)
        body = {'price': 12.5, 'price_type': 'unlocked', 'currency': 'EUR'}
        assert client.post('/api/v1/prices/preflight', json=body).status_code == 401
        headers = {'Authorization': 'Bearer ' + create_token('analyst@example.com')}
        response = client.post('/api/v1/prices/preflight', json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()['data'] == {'valid': True, 'issues': []}
        response = client.post('/api/v1/prices/preflight', json={**body, 'price': -1}, headers=headers)
        assert response.status_code == 200 and response.json()['data']['valid'] is False
        assert client.post('/api/v1/prices/preflight', json={}, headers=headers).status_code == 422
        # Standard JSON exponent overflows Python float: return a safe reason, never echo Infinity.
        response = client.post('/api/v1/prices/preflight',
                               content='{"price":1e400,"price_type":"unlocked","currency":"EUR"}',
                               headers={**headers, 'Content-Type': 'application/json'})
        assert response.status_code == 200
        assert response.json()['data']['issues'][0]['code'] == 'not_finite'
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
