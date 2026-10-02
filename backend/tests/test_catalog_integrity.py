import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from app.models.catalog import Model, Sku, ModelCompetitorMap
from app.models.channel import Channel
from app.services.catalog_integrity import diagnose_catalog
from app.main import app
from app.core.db import get_session
from app.core.security import create_token


@pytest.fixture
def session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_clean_catalog_is_valid_and_read_only(session):
    session.add_all([Model(id='target', marketing_code='T', display_name='Target'),
                     Model(id='rival', marketing_code='R', display_name='Rival'),
                     Channel(id='channel', name='Demo', country='Serbia')])
    session.flush()
    session.add(Sku(id='sku', model_id='target', channel_id='channel'))
    session.add(ModelCompetitorMap(id='map', model_id='target', competitor_id='rival'))
    session.commit()
    before = [row.model_dump() for row in session.exec(select(Sku)).all()]
    result = diagnose_catalog(session)
    assert result['valid'] is True
    assert result['counts']['orphan_skus'] == 0
    assert result['counts']['competitor_mappings'] == 1
    assert [row.model_dump() for row in session.exec(select(Sku)).all()] == before
    assert not session.new and not session.dirty and not session.deleted


def test_missing_relationships_and_self_mapping(session):
    session.add(Model(id='target', marketing_code='T', display_name='Target'))
    session.flush()
    session.add_all([Sku(id='orphan', model_id='absent', channel_id='absent'),
                     ModelCompetitorMap(id='bad', model_id='absent', competitor_id='other'),
                     ModelCompetitorMap(id='self', model_id='target', competitor_id='target')])
    session.commit()
    result = diagnose_catalog(session)
    assert result['valid'] is False
    assert result['sku_findings'] == [{'sku_id': 'orphan', 'reasons': ['missing_model', 'missing_channel']}]
    assert result['mapping_findings'] == [
        {'mapping_id': 'bad', 'reasons': ['missing_target_model', 'missing_competitor_model']},
        {'mapping_id': 'self', 'reasons': ['self_competitor']}]
    assert result['counts']['orphan_skus'] == 1
    assert result['counts']['invalid_competitor_mappings'] == 2


def test_empty_catalog_and_authentication(session):
    def override():
        yield session
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/models/integrity').status_code == 401
            response = client.get('/api/v1/models/integrity', headers={
                'Authorization': 'Bearer ' + create_token('analyst@example.com')})
            assert response.status_code == 200
            result = response.json()['data']
            assert result['valid'] is True
            assert all(value == 0 for value in result['counts'].values())
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
