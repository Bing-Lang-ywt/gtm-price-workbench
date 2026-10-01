"""EPREL (EU energy labelling registry) integration.

Discovers smartphone/tablet models registered under EU regulation 2023/1669
and downloads their official energy-label images (SVG + PDF). The public list
API is anonymous and needs no key; only the ``/search`` POST endpoint requires
an X-API-KEY (403), which we never use.

Reference (probed 2026-09-07):
  GET /api/products/{category}?supplierOrTrademark={brand}&_page=1&_limit=25
      -> { "size": <total>, "hits": [ {modelIdentifier, eprelRegistrationNumber,
         energyClass, repairabilityClass, deviceType, ratedBatteryCapacity, ...} ] }
  GET /api/products/{category}/{reg}/labels?noRedirect=true&format={SVG|PDF}
      -> { "address": "/labels/{category}/Label_{reg}.{ext}" }
  then download https://eprel.ec.europa.eu{address}
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from typing import Optional

# Smartphones + tablets share one category under EU 2023/1669.
EPREL_CATEGORY = "smartphonestablets20231669"
EPREL_BASE = "https://eprel.ec.europa.eu"

# Backend-relative default storage location (data/eprel/labels).
_LABELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "eprel",
    "labels",
)

_CTX = ssl.create_default_context()

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; price-monitor/1.0)",
    "Accept": "application/json",
}


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discover(supplier: str, page: int = 1, page_size: int = 25) -> dict:
    """Anonymous list search. Returns ``{"size": int, "hits": [...]}``."""
    url = (
        f"{EPREL_BASE}/api/products/{EPREL_CATEGORY}"
        f"?supplierOrTrademark={urllib.parse.quote(supplier)}"
        f"&_page={page}&_limit={page_size}&_sort=modelIdentifier"
    )
    return _get_json(url)


def iter_hits(supplier: str) -> list[dict]:
    """Page through the full result set for a supplier."""
    first = discover(supplier, page=1)
    hits = list(first.get("hits", []))
    size = first.get("size", len(hits))
    page = 2
    while len(hits) < size:
        chunk = discover(supplier, page=page)
        rows = chunk.get("hits", [])
        if not rows:
            break
        hits.extend(rows)
        page += 1
        time.sleep(0.2)
    return hits


def _resolve_label_path(reg: str, fmt: str) -> Optional[str]:
    api = (
        f"{EPREL_BASE}/api/products/{EPREL_CATEGORY}/{reg}"
        f"/labels?noRedirect=true&format={fmt}"
    )
    data = _get_json(api)
    addr = data.get("address", "")
    return addr if addr.startswith("/") else None


def download_labels(hit: dict, out_dir: str = _LABELS_DIR) -> tuple[Optional[str], Optional[str]]:
    """Download SVG + PDF for one EPREL hit. Returns (svg_rel, pdf_rel)."""
    import shutil

    os.makedirs(out_dir, exist_ok=True)
    reg = hit.get("eprelRegistrationNumber")
    model = hit.get("modelIdentifier", "")
    if not reg:
        return None, None
    safe = model.replace("/", "_")
    svg_rel = pdf_rel = None
    for fmt, ext in (("SVG", "svg"), ("PDF", "pdf")):
        addr = _resolve_label_path(reg, fmt)
        if not addr:
            continue
        req = urllib.request.Request(
            f"{EPREL_BASE}{addr}",
            headers={**_HEADERS, "Referer": f"{EPREL_BASE}/screen/product/{EPREL_CATEGORY}/{reg}"},
        )
        with urllib.request.urlopen(req, context=_CTX, timeout=30) as resp:
            blob = resp.read()
        fn = f"{safe}_{reg}.{ext}"
        with open(os.path.join(out_dir, fn), "wb") as f:
            f.write(blob)
        if ext == "svg":
            svg_rel = fn
        else:
            pdf_rel = fn
        time.sleep(0.2)
    return svg_rel, pdf_rel


def normalize(hit: dict) -> dict:
    """Flatten an EPREL hit into an ``EnergyLabel``-shaped dict."""
    oms = hit.get("onMarketStartDate")
    if isinstance(oms, (list, tuple)) and len(oms) == 3:
        on_market = f"{oms[0]:04d}-{oms[1]:02d}-{oms[2]:02d}"
    else:
        on_market = ""
    return {
        "supplier": (hit.get("supplierOrTrademark") or "").upper() or "DemoBrand",
        "model_identifier": hit.get("modelIdentifier", ""),
        "eprel_reg_no": str(hit.get("eprelRegistrationNumber", "")),
        "device_type": hit.get("deviceType", ""),
        "energy_class": hit.get("energyClass", ""),
        "repairability_class": hit.get("repairabilityClass", ""),
        "rated_battery_capacity": int(hit.get("ratedBatteryCapacity") or 0),
        "battery_endurance_cycles": int(hit.get("batteryEnduranceInCycles") or 0),
        "min_years_software_updates": int(hit.get("minYearsSoftwareUpdates") or 0),
        "ingress_protection_rating": str(hit.get("ingressProtectionRating") or ""),
        "is_foldable": bool(hit.get("isFoldable")),
        "operating_system": hit.get("operatingSystem", "") or "",
        "on_market_start_date": on_market,
    }


def sync_supplier(supplier: str, out_dir: str = _LABELS_DIR, session=None) -> int:
    """Discover + download + upsert a supplier's labels. Returns row count.

    Requires a SQLModel ``session`` (caller manages commit). Each model is
    upserted by (supplier, model_identifier).
    """
    from sqlmodel import select

    from app.models.energy import EnergyLabel

    hits = iter_hits(supplier)
    count = 0
    for hit in hits:
        base = normalize(hit)
        svg_rel, pdf_rel = download_labels(hit, out_dir)
        existing = session.exec(
            select(EnergyLabel).where(
                EnergyLabel.supplier == base["supplier"],
                EnergyLabel.model_identifier == base["model_identifier"],
            )
        ).first()
        if existing:
            for k, v in base.items():
                setattr(existing, k, v)
            existing.label_svg_rel = svg_rel or existing.label_svg_rel
            existing.label_pdf_rel = pdf_rel or existing.label_pdf_rel
            existing.raw_json = json.dumps(hit, ensure_ascii=False)
        else:
            existing = EnergyLabel(
                **base,
                label_svg_rel=svg_rel or "",
                label_pdf_rel=pdf_rel or "",
                raw_json=json.dumps(hit, ensure_ascii=False),
            )
            session.add(existing)
        count += 1
    return count
