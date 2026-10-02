import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_session
from app.core.security import create_token
from app.services.alert_preview import preview_rules


def sample(amount=100, previous=None, **kwargs):
    return {'sku_id':'s', 'model_id':'m', 'channel_id':'c', 'price_type':'unlocked',
            'amount_eur':amount, 'previous_amount_eur':previous, **kwargs}


def evaluation(rule, value):
    return preview_rules([rule], [value])['results'][0]['evaluations'][0]


@pytest.mark.parametrize('condition,amount,expected', [
    ('below',99,True), ('below',100,False), ('below',101,False),
    ('above',99,False), ('above',100,False), ('above',101,True),
])
def test_absolute_threshold_boundaries(condition, amount, expected):
    assert evaluation({'condition_type':condition,'threshold':100},sample(amount))['matched'] is expected


@pytest.mark.parametrize('amount,previous,expected,reason', [
    (90,100,True,'condition_matched'), (110,100,True,'condition_matched'),
    (91,100,False,'condition_not_met'), (100,None,False,'no_positive_previous_price'),
    (100,0,False,'no_positive_previous_price'),
])
def test_delta_boundaries_and_missing_previous(amount, previous, expected, reason):
    result=evaluation({'condition_type':'delta_pct','threshold':10},sample(amount,previous))
    assert result['matched'] is expected and result['reason']==reason


def test_new_entry_zero_price_and_duplicate_suppression():
    rule={'condition_type':'new_entry'}
    data=sample(0,is_new_entry=True)
    report=preview_rules([rule],[data,dict(data),sample(1)])
    assert report['matched_count']==1
    assert report['results'][1]['duplicate_of']==0
    assert report['results'][1]['evaluations'][0]['reason']=='duplicate_sample'
    assert report['results'][2]['evaluations'][0]['matched'] is False


def test_compound_scope_legacy_scope_inactive_and_price_type():
    base={'condition_type':'below','threshold':200}
    assert evaluation({**base,'sku_id':'other'},sample())['reason']=='scope_mismatch'
    assert evaluation({**base,'scope_type':'model','scope_id':'m'},sample())['matched'] is True
    assert evaluation({**base,'scope_type':'sku','scope_id':'other','model_id':'m'},sample())['matched'] is True
    assert evaluation({**base,'is_active':False},sample())['reason']=='inactive_rule'
    assert evaluation({**base,'price_type':'contract_monthly'},sample())['reason']=='price_type_mismatch'


@pytest.mark.parametrize('rule,value', [
    ({'condition_type':'unknown'},sample()),
    ({'condition_type':'below','threshold':float('nan')},sample()),
    ({'condition_type':'above','threshold':-1},sample()),
    ({'condition_type':'below','threshold':True},sample()),
    ({'condition_type':'below','threshold':10},sample(float('inf'))),
    ({'condition_type':'below','threshold':10},sample(-1)),
    ({'condition_type':'new_entry','threshold':10},sample()),
    ({'condition_type':'new_entry'},sample(100,90,is_new_entry=True)),
    ({'condition_type':'new_entry','scope_type':'segment','scope_id':'mid'},sample()),
    ({'condition_type':'new_entry'},sample(sku_id='')),
])
def test_invalid_inputs_rejected(rule,value):
    with pytest.raises(ValueError):preview_rules([rule],[value])


def test_api_requires_auth_and_cannot_access_database_or_notifier(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Offline preview touched a side effect')
    from app.alerting import notifier, rule_engine
    monkeypatch.setattr(notifier,'notify',forbidden)
    monkeypatch.setattr(rule_engine,'notify',forbidden)
    previous=dict(app.dependency_overrides)
    app.dependency_overrides[get_session]=forbidden
    try:
        client=TestClient(app)
        body={'rules':[{'condition_type':'above','threshold':90}],'samples':[sample()]}
        assert client.post('/api/v1/alert-rules/preview',json=body).status_code==401
        headers={'Authorization':'Bearer '+create_token('analyst@example.com')}
        response=client.post('/api/v1/alert-rules/preview',json=body,headers=headers)
        assert response.status_code==200 and response.json()['data']['matched_count']==1
        assert client.post('/api/v1/alert-rules/preview',json={**body,'rules':[]},headers=headers).status_code==422
        bad={**body,'samples':[sample(-1)]}
        assert client.post('/api/v1/alert-rules/preview',json=bad,headers=headers).status_code==422
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
