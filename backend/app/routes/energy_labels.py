"""Energy-label (EPREL) API + read-only HTML grid view.

JSON endpoints are auth-gated like the rest of the API. The ``/view`` HTML
page and ``/{id}/image`` stream are intentionally public so the dashboard can
be opened without a token — this is an internal competitive-intelligence tool.

NOTE: literal routes (``/view``) MUST be declared before the ``/{label_id}``
parameterised route, otherwise FastAPI matches ``view`` as a label id.
"""

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from sqlmodel import select, Session

from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user
from app.models.energy import EnergyLabel

router = APIRouter(prefix="/energy-labels", tags=["energy-labels"])

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(os.path.dirname(_HERE))  # .../backend
_LABELS_DIR = os.path.join(_BACKEND_ROOT, "data", "eprel", "labels")

EC_COLOR = {
    "A": "#00a651", "B": "#50b848", "C": "#bfd730", "D": "#fff200",
    "E": "#fdb913", "F": "#f37021", "G": "#ed1c24",
}


def _build_query(supplier, device_type, energy_class, q):
    stmt = select(EnergyLabel)
    if supplier:
        stmt = stmt.where(EnergyLabel.supplier == supplier.upper())
    if device_type:
        stmt = stmt.where(EnergyLabel.device_type == device_type.upper())
    if energy_class:
        stmt = stmt.where(EnergyLabel.energy_class == energy_class.upper())
    if q:
        stmt = stmt.where(EnergyLabel.model_identifier.ilike(f"%{q}%"))
    return stmt


@router.get("")
def list_energy_labels(
    supplier: str = Query(None),
    device_type: str = Query(None),
    energy_class: str = Query(None),
    q: str = Query(None),
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    rows = session.exec(_build_query(supplier, device_type, energy_class, q)).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "supplier": r.supplier,
            "model_identifier": r.model_identifier,
            "eprel_reg_no": r.eprel_reg_no,
            "device_type": r.device_type,
            "energy_class": r.energy_class,
            "repairability_class": r.repairability_class,
            "marketing_code": r.marketing_code,
            "rated_battery_capacity": r.rated_battery_capacity,
            "battery_endurance_cycles": r.battery_endurance_cycles,
            "min_years_software_updates": r.min_years_software_updates,
            "ingress_protection_rating": r.ingress_protection_rating,
            "is_foldable": r.is_foldable,
            "operating_system": r.operating_system,
            "on_market_start_date": r.on_market_start_date,
            "has_svg": bool(r.label_svg_rel),
            "has_pdf": bool(r.label_pdf_rel),
            "image_url": f"/api/v1/energy-labels/{r.id}/image?fmt=svg" if r.label_svg_rel else None,
            "pdf_url": f"/api/v1/energy-labels/{r.id}/image?fmt=pdf" if r.label_pdf_rel else None,
        })
    out.sort(key=lambda x: (x["supplier"], x["device_type"], x["energy_class"], x["model_identifier"]))
    return ok(out)


@router.get("/view", response_class=HTMLResponse)
def energy_labels_view(
    supplier: str = Query(None),
    device_type: str = Query(None),
    energy_class: str = Query(None),
    q: str = Query(None),
    session: Session = Depends(get_session),
):
    rows = session.exec(_build_query(supplier, device_type, energy_class, q)).all()
    rows.sort(key=lambda r: (r.supplier, r.device_type, r.energy_class, r.model_identifier))

    def ec_badge(v):
        c = EC_COLOR.get(v, "#555")
        tc = "#111" if v in ("A", "B", "C", "D") else "#fff"
        return f'<span style="background:{c};color:{tc};font-weight:700;padding:2px 8px;border-radius:4px">{v or "-"}</span>'

    cards = []
    for r in rows:
        svg = ""
        if r.label_svg_rel and os.path.exists(os.path.join(_LABELS_DIR, r.label_svg_rel)):
            with open(os.path.join(_LABELS_DIR, r.label_svg_rel), "r", encoding="utf-8", errors="replace") as f:
                svg = f.read()
            svg = svg.replace('<?xml version="1.0" encoding="UTF-8"?>', "")
            svg = svg.replace('<svg ', '<svg style="max-width:100%;height:auto;max-height:240px;" ', 1)
            svg = re.sub(r'\swidth="[^"]+"', '', svg, count=1)
            svg = re.sub(r'\sheight="[^"]+"', '', svg, count=1)
        else:
            svg = '<div style="color:#c0392b;font-size:12px">标签图缺失</div>'
        pdf_link = (
            f'<a href="/api/v1/energy-labels/{r.id}/image?fmt=pdf" target="_blank" '
            f'style="font-size:11px;color:#2563eb">PDF 下载</a>'
            if r.label_pdf_rel else '<span style="font-size:11px;color:#999">无 PDF</span>'
        )
        meta = (
            f"能效 {ec_badge(r.energy_class)} &nbsp; 可维修 {ec_badge(r.repairability_class)}<br>"
            f"电池 {r.rated_battery_capacity or '-'} mAh · 循环 {r.battery_endurance_cycles or '-'}<br>"
            f"系统更新 {r.min_years_software_updates or '-'} 年 · 防护 {r.ingress_protection_rating or '-'}<br>"
            f"{'折叠屏 · ' if r.is_foldable else ''}上市 {r.on_market_start_date or '-'}<br>"
            f"EPREL {r.eprel_reg_no} · {pdf_link}"
        )
        cards.append(f"""<div class="card">
  <div class="model">{r.model_identifier}</div>
  <div class="sup">{r.supplier} · {('手机' if r.device_type=='SMARTPHONE' else '平板')}</div>
  <div class="svgwrap">{svg}</div>
  <div class="meta">{meta}</div>
</div>""")

    def opt(name, val, cur):
        sel = " selected" if cur == val else ""
        return f'<option value="{val}"{sel}>{name}</option>'
    sup_opts = "".join(opt(s, s, supplier) for s in ["", "DemoBrand", "SAMSUNG", "XIAOMI"])
    dev_opts = "".join(
        opt(n, v, device_type) for n, v in [("全部类型", ""), ("手机", "SMARTPHONE"), ("平板", "TABLET")]
    )
    ec_opts = "".join(opt(n, v, energy_class) for n, v in [("全部等级", "")] + [(c, c) for c in "ABCDEFG"])

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>能源标签 · EPREL</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:20px;background:#0f1115;color:#e6e6e6;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:#9aa0a6;font-size:13px;margin-bottom:14px}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px;align-items:center}}
.bar select,.bar input{{background:#1b1e24;color:#e6e6e6;border:1px solid #2a2d33;
  border-radius:6px;padding:6px 8px;font-size:13px}}
.bar input{{width:160px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}}
.card{{border:1px solid #2a2d33;border-radius:8px;padding:10px;background:#16191f;
  display:flex;flex-direction:column;align-items:center;break-inside:avoid}}
.card .model{{font-weight:700;font-size:14px}}
.card .sup{{font-size:11px;color:#7fd1ff;margin-bottom:8px}}
.card .svgwrap{{width:100%;display:flex;justify-content:center;margin-bottom:8px}}
.card .meta{{font-size:11px;color:#cfd3da;line-height:1.5;text-align:center}}
.legend{{font-size:12px;color:#9aa0a6;margin-top:18px}}
.legend b{{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:-2px;margin:0 3px 0 8px}}
</style></head><body>
<h1>DemoBrand / 竞品 设备能源标签 — EPREL（EU 2023/1669）</h1>
<div class="sub">数据源 EPREL Public website · 共 {len(rows)} 个型号 · 标签图经后端下载缓存</div>
<form class="bar" method="get">
  <select name="supplier">{sup_opts}</select>
  <select name="device_type">{dev_opts}</select>
  <select name="energy_class">{ec_opts}</select>
  <input name="q" placeholder="型号关键字" value="{q or ''}">
  <button type="submit" style="background:#2563eb;color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer">筛选</button>
</form>
<div class="grid">{''.join(cards)}</div>
<div class="legend">能效/可维修等级（EU A–G）：{''.join(f'<b style="background:{EC_COLOR[k]}"></b>{k}' for k in "ABCDEFG")}</div>
</body></html>"""
    return HTMLResponse(html)


@router.get("/{label_id}")
def get_energy_label(
    label_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    r = session.get(EnergyLabel, label_id)
    if not r:
        raise HTTPException(status_code=404, detail="Energy label not found")
    return ok({c.name: getattr(r, c.name) for c in EnergyLabel.__table__.columns})


@router.get("/{label_id}/image")
def label_image(label_id: str, fmt: str = "svg", session: Session = Depends(get_session)):
    """Stream the stored label image (public). fmt=svg|pdf."""
    r = session.get(EnergyLabel, label_id)
    if not r:
        raise HTTPException(status_code=404, detail="Energy label not found")
    rel = r.label_svg_rel if fmt.lower() == "svg" else r.label_pdf_rel
    if not rel:
        raise HTTPException(status_code=404, detail=f"No {fmt} label stored")
    path = os.path.join(_LABELS_DIR, rel)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Label file missing on disk")
    media = "image/svg+xml" if fmt.lower() == "svg" else "application/pdf"
    return FileResponse(path, media_type=media, filename=rel)
