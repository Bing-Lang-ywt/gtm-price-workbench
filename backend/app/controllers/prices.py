from app.services.prices import (
    latest_snapshot_service,
    price_history_service,
    create_manual_price,
    date_counts_service,
    promotions_service,
    model_trend_service,
)


def latest_controller(session, channel_id, model_id, country, price_type, page, limit):
    return latest_snapshot_service(
        session, channel_id, model_id, country, price_type, page, limit
    )


def snapshot_by_date_controller(
    session, date, channel_id, model_id, country, price_type, window_days
):
    return latest_snapshot_service(
        session,
        channel_id,
        model_id,
        country,
        price_type,
        1,
        2000,
        as_of_date=date,
        window_days=window_days,
    )


def date_counts_controller(session):
    return date_counts_service(session)


def promotions_controller(session, from_, to, threshold, channel_id, model_id, country, max_drop=0.6):
    return promotions_service(
        session, from_, to, threshold, channel_id, model_id, country, max_drop
    )


def model_trend_controller(session, model_id, price_type, country):
    return model_trend_service(session, model_id, price_type, country)


def history_controller(session, sku_id, channel_id, price_type, from_, to, page, limit):
    return price_history_service(
        session, sku_id, channel_id, price_type, from_, to, page, limit
    )


def create_manual_controller(
    session, sku_id, channel_id, price_type, price, currency, in_stock=True
):
    return create_manual_price(
        session, sku_id, channel_id, price_type, price, currency, in_stock=in_stock
    )
