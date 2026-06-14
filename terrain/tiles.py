"""
tiles.py -- hillshade tile endpoint for the Leaflet map.

Serves /api/tiles/<z>/<x>/<y>.png for L.CRS.Simple, where one map unit ==
one heightmap pixel and scale(zoom) = 2**zoom (so a 256px tile covers
256 / 2**z heightmap pixels; z may be negative when zoomed out).

The heightmap comes from settings.WORLDFORGE_HEIGHTMAP (a .npy produced by
`manage.py erode`); the shaded uint8 image is computed once per file mtime
and cached in process memory. Later this becomes per-project state and the
frontend bumps ?v= after each erosion run to invalidate browser caches.

urls.py:
    from terrain.tiles import tile
    re_path(r"^api/tiles/(?P<z>-?\\d+)/(?P<x>\\d+)/(?P<y>\\d+)\\.png$", tile)

settings.py:
    WORLDFORGE_HEIGHTMAP = BASE_DIR / "runs" / "latest" / "final.npy"
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import torch
from django.conf import settings
from django.http import Http404, HttpResponse
from PIL import Image

from .viz import hillshade

_cache: dict = {"mtime": None, "shade": None, "size": 0}
TILE = 256


def _shaded() -> np.ndarray:
    path = Path(settings.WORLDFORGE_HEIGHTMAP)
    if not path.exists():
        raise Http404("No heightmap yet -- run `manage.py erode` first.")
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        z = torch.from_numpy(np.load(path)).float()
        shade = (hillshade(z).numpy() * 255).astype(np.uint8)
        _cache.update(mtime=mtime, shade=shade, size=shade.shape[0])
    return _cache["shade"]


def tile(request, z: str, x: str, y: str) -> HttpResponse:
    z, x, y = int(z), int(x), int(y)
    shade = _shaded()
    n = shade.shape[0]

    # heightmap pixels covered by one tile at this zoom
    span = TILE * 2 ** (-z) if z < 0 else TILE // (2 ** min(z, 8))
    span = max(int(span), 1)
    x0, y0 = x * span, y * span
    if x0 >= n or y0 >= n or x < 0 or y < 0:
        raise Http404
    crop = shade[y0: min(y0 + span, n), x0: min(x0 + span, n)]

    img = Image.new("L", (span, span), 0)
    img.paste(Image.fromarray(crop), (0, 0))
    img = img.resize((TILE, TILE), Image.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    resp = HttpResponse(buf.getvalue(), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=60"
    return resp
