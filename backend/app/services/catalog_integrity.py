"""Read-only relationship diagnostics; does not repair or crawl the catalog."""
from sqlmodel import select
from app.models.catalog import Model, Sku, ModelCompetitorMap
from app.models.channel import Channel


def diagnose_catalog(session):
    model_ids = set(session.exec(select(Model.id)).all())
    channel_ids = set(session.exec(select(Channel.id)).all())
    skus = session.exec(select(Sku).order_by(Sku.id)).all()
    mappings = session.exec(select(ModelCompetitorMap).order_by(ModelCompetitorMap.id)).all()
    sku_findings = []
    for sku in skus:
        reasons = []
        if sku.model_id not in model_ids:
            reasons.append('missing_model')
        if sku.channel_id not in channel_ids:
            reasons.append('missing_channel')
        if reasons:
            sku_findings.append({'sku_id': sku.id, 'reasons': reasons})
    mapping_findings = []
    for mapping in mappings:
        reasons = []
        if mapping.model_id not in model_ids:
            reasons.append('missing_target_model')
        if mapping.competitor_id not in model_ids:
            reasons.append('missing_competitor_model')
        if mapping.model_id == mapping.competitor_id:
            reasons.append('self_competitor')
        if reasons:
            mapping_findings.append({'mapping_id': mapping.id, 'reasons': reasons})
    return {
        'counts': {'models': len(model_ids), 'channels': len(channel_ids), 'skus': len(skus),
                   'competitor_mappings': len(mappings), 'orphan_skus': len(sku_findings),
                   'invalid_competitor_mappings': len(mapping_findings)},
        'valid': not sku_findings and not mapping_findings,
        'sku_findings': sku_findings, 'mapping_findings': mapping_findings,
    }
