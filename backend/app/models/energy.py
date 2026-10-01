"""EPREL EU energy-label registry for monitored device lineups.

Each row is one device model registered in the European energy labelling
registry (EPREL, regulation EU 2023/1669 for smartphones & tablets). The
``model_identifier`` is the manufacturer's EPREL device code (e.g. ``MTN-NX1M``)
and ``eprel_reg_no`` is the registration number used to fetch the official
label image. ``label_svg_rel`` / ``label_pdf_rel`` point at files under
``data/eprel/labels/``.

The monitor's own ``models`` table uses marketing codes (``H600``, ``MagicV6``…)
which do **not** always coincide with EPREL device codes — newer monitored
models (DemoBrand 600 series, Magic V6) are frequently not yet registered in EPREL.
``marketing_code`` is therefore nullable and only populated when an explicit
mapping is known; the energy-label view is primarily a standalone reference for
the brand's registered lineup.
"""

import uuid

from sqlmodel import SQLModel, Field

from app.core.time import utcnow


class EnergyLabel(SQLModel, table=True):
    __tablename__ = "energy_labels"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    supplier: str = Field(index=True, default="")          # DemoBrand / SAMSUNG / XIAOMI
    model_identifier: str = Field(index=True, default="")  # EPREL modelIdentifier
    eprel_reg_no: str = Field(default="")
    device_type: str = Field(default="")                   # SMARTPHONE / TABLET
    energy_class: str = Field(default="")                  # A–G
    repairability_class: str = Field(default="")           # A–G
    marketing_code: str = Field(default="")                # project model code if mapped

    rated_battery_capacity: int = Field(default=0)         # mAh
    battery_endurance_cycles: int = Field(default=0)
    min_years_software_updates: int = Field(default=0)
    ingress_protection_rating: str = Field(default="")
    is_foldable: bool = Field(default=False)
    operating_system: str = Field(default="")
    on_market_start_date: str = Field(default="")          # ISO yyyy-mm-dd

    label_svg_rel: str = Field(default="")                 # filename under data/eprel/labels
    label_pdf_rel: str = Field(default="")
    raw_json: str = Field(default="")                      # full EPREL hit (for future fields)
    fetched_at: str = Field(default_factory=lambda: utcnow().isoformat())
