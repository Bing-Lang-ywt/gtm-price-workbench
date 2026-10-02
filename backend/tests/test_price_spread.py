import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from app.models.catalog import Model, Sku
from app.models.channel import Channel
from app.models.price import Price
from app.services.price_spread import latest_price_spread
from app.main import app
from app.core.db import get_session
from app.core.security import create_token


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Model(id='m', marketing_code='D', display_name='Demo'),
                         Model(id='empty', marketing_code='E', display_name='Empty'),
                         Channel(id='a', name='Demo A', country='Serbia'),
                         Channel(id='b', name='Demo B', country='Croatia')])
        session.flush()
        session.add_all([Sku(id='a1', model_id='m', channel_id='a'),
                         Sku(id='a2', model_id='m', channel_id='a'),
                         Sku(id='b1', model_id='m', channel_id='b')])
        session.commit()
        yield session
    engine.dispose()


def add(session, pid, sku, amount, date, kind='unlocked', meta=None):
    session.add(Price(id=pid, sku_id=sku, channel_id=sku[0], price_type=kind,
                      price=amount, amount_eur=amount, currency='EUR', captured_at=date, meta=meta))
    session.commit()


def row(session, **kwargs):
    return next(x for x in latest_price_spread(session, **kwargs)['items'] if x['model_id']=='m')


def test_latest_selected_type_overrides_old_manual_price(db):
    add(db, 'old', 'a1', 100, '2025-01-01T00:00:00Z', meta='{"source":"manual"}')
    add(db, 'new', 'a1', 300, '2025-01-02T00:00:00Z')
    add(db, 'monthly', 'a1', 10, '2025-01-03T00:00:00Z', 'contract_monthly')
    add(db, 'b', 'b1', 400, '2025-01-02T00:00:00Z')
    result = row(db)
    assert result['min_eur']==300 and result['max_eur']==400 and result['spread_eur']==100
    assert result['channel_count']==2
    assert row(db, price_type='contract_monthly')['spread_eur'] is None
    assert not db.new and not db.dirty and not db.deleted


def test_missing_prices_and_single_channel_do_not_create_zero_spread(db):
    result = row(db)
    assert result['min_eur'] is None and result['spread_eur'] is None
    add(db, 'a1', 'a1', 300, '2025-01-01T00:00:00Z')
    add(db, 'a2', 'a2', 250, '2025-01-01T00:00:00Z')
    result = row(db)
    assert result['channel_count']==1 and result['min_eur']==250 and result['spread_eur'] is None
    assert result['channels'][0]['sku_samples']==2


def test_latest_invalid_amount_does_not_fall_back_to_old_price(db):
    add(db, 'old', 'a1', 300, '2025-01-01T00:00:00Z')
    add(db, 'new', 'a1', 0, '2025-01-02T00:00:00Z')
    add(db, 'b', 'b1', 400, '2025-01-02T00:00:00Z')
    assert row(db)['channel_count']==1 and row(db)['min_eur']==400


def test_offsets_ties_and_bad_timestamps(db):
    add(db, 'earlier', 'a1', 100, '2025-01-02T11:00:00+02:00')
    add(db, 'later-a', 'a1', 300, '2025-01-02T10:00:00Z')
    add(db, 'later-z', 'a1', 350, '2025-01-02T10:00:00Z')
    add(db, 'invalid', 'b1', 400, 'not-a-date')
    result = latest_price_spread(db)
    assert row(db)['min_eur']==350
    assert result['skipped_invalid_timestamps']==1
    assert latest_price_spread(db, model_id='unknown')['items']==[]


def test_endpoint_auth_filter_and_invalid_type(db):
    def override():
        yield db
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session]=override
    try:
        client=TestClient(app)
        assert client.get('/api/v1/comparison/spread').status_code==401
        headers={'Authorization':'Bearer '+create_token('analyst@example.com')}
        response=client.get('/api/v1/comparison/spread?model_id=m',headers=headers)
        assert response.status_code==200
        assert len(response.json()['data']['items'])==1
        assert client.get('/api/v1/comparison/spread?price_type=unknown',headers=headers).status_code==422
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
