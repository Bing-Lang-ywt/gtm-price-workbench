"""Combined EPREL energy-label pack (phone + tablet) — public download page.

Two pre-built combined PDFs (one per device category) produced by the EPREL
label-download task live in ``data/eprel/pack/``. This module serves a small
feature page that lists them with an inline preview link + a download button.

Public, like the energy-labels grid — this is an internal competitive-intel
tool and the PDFs carry no sensitive data.
"""

import io
import os
import re
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter(prefix="/energy-label-pack", tags=["energy-label-pack"])

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(os.path.dirname(_HERE))  # .../backend
_PACK_DIR = os.path.join(_BACKEND_ROOT, "data", "eprel", "pack")
_LABELS_DIR = os.path.join(_BACKEND_ROOT, "data", "eprel", "labels")
_ZIP_NAME = "DemoBrand 能源标签合集（单品）.zip"

# slug -> (filename, title, subtitle)
_PACK_FILES = {
    "phone": ("demobrand_labels_phone.pdf", "DemoBrand 手机能源标签合集", "智能手机 · Smartphone"),
    "tablet": ("demobrand_labels_tablet.pdf", "DemoBrand 平板能源标签合集", "平板 · Tablet"),
}


def _resolve(slug: str):
    if slug not in _PACK_FILES:
        raise HTTPException(status_code=404, detail="Unknown pack")
    fname, title, sub = _PACK_FILES[slug]
    path = os.path.join(_PACK_DIR, fname)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Pack file missing on disk")
    return path, fname, title, sub


def _page_count(path: str) -> int:
    """Best-effort page count from the PDF's /Type /Page objects."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        # Count leaf page objects, not the /Pages tree node.
        return len(re.findall(rb"/Type\s*/Page[^s]", data))
    except Exception:
        return 0


@router.get("/{slug}/inline")
def pack_inline(slug: str):
    """Serve the PDF inline so the browser can render a preview."""
    path, fname, _, _ = _resolve(slug)
    return FileResponse(path, media_type="application/pdf")


@router.get("/{slug}/download")
def pack_download(slug: str):
    """Force a download with a clean filename."""
    path, fname, title, _ = _resolve(slug)
    download_name = f"{title}.pdf"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=download_name,
        content_disposition_type="attachment",
    )


@router.get("/zip")
def pack_zip():
    """Bundle every individual product energy-label PDF into one ZIP."""
    if not os.path.isdir(_LABELS_DIR):
        raise HTTPException(status_code=404, detail="Labels directory missing")
    pdfs = sorted(
        f for f in os.listdir(_LABELS_DIR) if f.lower().endswith(".pdf")
    )
    if not pdfs:
        raise HTTPException(status_code=404, detail="No individual label PDFs found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in pdfs:
            zf.write(os.path.join(_LABELS_DIR, name), arcname=name)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(_ZIP_NAME)}"
        },
    )


@router.get("/page", response_class=HTMLResponse)
def pack_page():
    cards = []
    for slug, (fname, title, sub) in _PACK_FILES.items():
        path = os.path.join(_PACK_DIR, fname)
        if not os.path.exists(path):
            cards.append(f"""<div class="card missing">
  <div class="title">{title}</div>
  <div class="sub">{sub}</div>
  <div class="warn">文件缺失：{fname}</div>
</div>""")
            continue
        size_kb = os.path.getsize(path) // 1024
        pages = _page_count(path) or "-"
        cards.append(f"""<div class="card">
  <div class="title">{title}</div>
  <div class="sub">{sub}</div>
  <div class="stat">文件 {fname} · {size_kb:,} KB · {pages} 页</div>
  <div class="btns">
    <a class="btn view" href="/api/v1/energy-label-pack/{slug}/inline" target="_blank" rel="noopener">预览</a>
    <a class="btn dl" href="/api/v1/energy-label-pack/{slug}/download">下载 PDF</a>
  </div>
</div>""")

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>能源标签合集 · 下载</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:28px;background:#0f1115;color:#e6e6e6;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
h1{{font-size:22px;margin:0 0 6px}}
.sub{{color:#9aa0a6;font-size:13px;margin-bottom:22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}}
.card{{border:1px solid #2a2d33;border-radius:10px;padding:18px;background:#16191f;
  display:flex;flex-direction:column;gap:6px}}
.card.missing{{border-color:#5a2a2a}}
.title{{font-weight:700;font-size:16px}}
.sub{{color:#7fd1ff;font-size:12px}}
.stat{{font-size:12px;color:#cfd3da;margin:6px 0 4px}}
.btns{{display:flex;gap:10px;margin-top:8px}}
.btn{{text-decoration:none;font-size:13px;font-weight:600;padding:8px 16px;border-radius:7px;
  text-align:center;transition:opacity .15s}}
.btn.view{{background:#1f2937;color:#e6e6e6;border:1px solid #33405a}}
.btn.dl{{background:#2563eb;color:#fff}}
.btn:hover{{opacity:.85}}
.warn{{color:#f87171;font-size:13px}}
.foot{{margin-top:26px;font-size:12px;color:#6b7280}}
a.back{{color:#7fd1ff;font-size:13px;text-decoration:none}}
</style></head><body>
<h1>能源标签合集（EU 能效标签 · EPREL）</h1>
<div class="sub">EPREL 欧盟能效标签下载任务产出 · 按设备类别合并的 PDF · 公开下载</div>
<div class="grid">{''.join(cards)}</div>
<div class="foot">
  数据源 EPREL Public website（欧盟能效标签注册库，法规 EU 2023/1669）。
  单型号标签详见 <a class="back" href="/energy-labels">能源标签矩阵</a>。
</div>
</body></html>"""
    return HTMLResponse(html)
