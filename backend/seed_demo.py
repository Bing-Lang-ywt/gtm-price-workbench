"""Generate fictional data in an empty local database without crawling sites."""
from datetime import timedelta
from sqlmodel import Session, select
from app.core.db import engine, init_db
from app.core.time import utcnow
from app.models.catalog import Model, ModelCompetitorMap, Sku
from app.models.channel import Channel
from app.models.price import Price, FxRate


def seed_demo():
    init_db()
    with Session(engine) as session:
        if session.exec(select(Model)).first() or session.exec(select(Channel)).first():
            raise RuntimeError('Demo seed requires an empty database; existing data was left unchanged')
        models = [Model(id='demo-target', marketing_code='DEMO1', display_name='DemoBrand One',
                        brand='DemoBrand', is_target=True, price_band_anchor=400),
                  Model(id='demo-rival', marketing_code='RIVAL1', display_name='ExampleBrand Two',
                        brand='ExampleBrand', is_target=False, price_band_anchor=400)]
        channels = [Channel(id='demo-shop-rs', name='Demo Shop RS', country='Serbia',
                            type='market', enabled=False, base_url='https://shop.example.invalid'),
                    Channel(id='demo-shop-hr', name='Demo Shop HR', country='Croatia',
                            type='market', enabled=False, base_url='https://shop.example.invalid')]
        session.add_all(models + channels)
        session.flush()
        session.add(ModelCompetitorMap(model_id='demo-target', competitor_id='demo-rival'))
        session.add(FxRate(date=utcnow().date().isoformat(), currency='EUR', rate_to_eur=1))
        for mi, model in enumerate(models):
            for ci, channel in enumerate(channels):
                sku = Sku(id=f'demo-sku-{mi}-{ci}', model_id=model.id, channel_id=channel.id,
                          product_url='https://shop.example.invalid/product', note='Fictional demo data')
                session.add(sku)
                session.flush()
                for day in range(7):
                    amount = 399 + mi*20 + ci*15 - day*2
                    session.add(Price(sku_id=sku.id, channel_id=channel.id, price_type='unlocked',
                                      price=amount, amount_eur=amount, currency='EUR',
                                      captured_at=(utcnow()-timedelta(days=6-day)).isoformat(),
                                      meta='{"source":"synthetic_demo"}'))
        session.commit()
    print('Created 2 fictional models, 2 disabled channels, 4 SKUs and 28 prices')


if __name__ == '__main__':
    seed_demo()
