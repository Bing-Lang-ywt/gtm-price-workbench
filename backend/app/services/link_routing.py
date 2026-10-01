"""Public demo routing. Private channel/product mappings are not distributed."""
from urllib.parse import quote_plus

GIGATRON_URLS = {}
CHANNEL_MODEL_PDP = {}
CHANNEL_LISTING_URLS = {}


def resolve_link(channel_name: str, code: str, model_name: str, brand: str):
    pdp = CHANNEL_MODEL_PDP.get(channel_name, {}).get(code, "")
    template = CHANNEL_LISTING_URLS.get(channel_name)
    listing = template.format(q=quote_plus(model_name), brand=brand) if template else ""
    return pdp, listing
