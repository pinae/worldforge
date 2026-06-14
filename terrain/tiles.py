"""
tiles.py -- hillshade tile endpoint for the Leaflet CRS.Simple map.

Coordinate model (the part that was wrong before)
-------------------------------------------------
With L.CRS.Simple and a TileLayer, Leaflet tiles the PROJECTED plane, not
just the positive quadrant. At zoom z the projection scale is 2**z screen
px per map unit, so one 256px tile spans  256 / 2**z  map units == that many
heightmap pixels (our map unit = 1 px). Leaflet's tile (tx, ty) covers:

    map-x in [tx*span, (tx+1)*span)
    map-y in [ty*span, (ty+1)*span)      (Leaflet tile y increases downward)

Our heightmap pixel rows also increase downward, and we place the image with
its top-left at map (0,0). So tile (tx,ty) maps DIRECTLY to heightmap slice
[ty*span : .., tx*span : ..] -- but ONLY for tx,ty >= 0. Leaflet also asks
for negative indices and indices past the map edge (it doesn't know the
bounds); those are legitimately empty and must return a blank 200 tile, not
a 404 -- a 404 makes Leaflet log errors and retry.

So the fixes vs. the first version:
  * accept negative tx/ty and out-of-range tiles, return transparent tiles
  * correct span = 256 / 2**z  (works for negative z too; no integer floor)
  * set TileLayer bounds on the frontend so far-flung tiles aren't requested
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from django.conf import settings
from django.http import HttpResponse
from PIL import Image

from .viz import hillshade

TILE = 256
_cache: dict = {"mtime": None, "shade": None}


def _shaded() -> np.ndarray:
    """uint8 (N,N) hillshade of the current heightmap, memoised by mtime."""
    path = Path(settings.WORLDFORGE_HEIGHTMAP)
    if not path.exists():
        raise FileNotFoundError(f"heightmap not found: {path}")
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        z = torch.from_numpy(np.load(path)).float()
        _cache.update(mtime=mtime,
                      shade=(hillshade(z).numpy() * 255).astype(np.uint8))
    return _cache["shade"]


def _tile_array(shade: np.ndarray, z: int, tx: int, ty: int
                ) -> Optional[np.ndarray]:
    """Return the (TILE,TILE) uint8 tile, or None if it lies outside the map.

    Pure function -- no Django, no HTTP -- so `manage.py tiletest` and the
    view share identical math.
    """
    n = shade.shape[0]
    span = TILE / (2.0 ** z)  # heightmap px per tile (float ok)
    x0 = tx * span
    y0 = ty * span
    if x0 >= n or y0 >= n or x0 + span <= 0 or y0 + span <= 0:
        return None  # fully outside -> empty tile

    # source slice (clamped to the map), then resize the covered part into
    # its correct sub-rectangle of the tile.
    sx0, sy0 = max(int(round(x0)), 0), max(int(round(y0)), 0)
    sx1 = min(int(round(x0 + span)), n)
    sy1 = min(int(round(y0 + span)), n)
    crop = shade[sy0:sy1, sx0:sx1]
    if crop.size == 0:
        return None

    tile = np.zeros((TILE, TILE), np.uint8)
    # where does this crop land within the tile?
    scale = TILE / span
    dx0 = int(round((sx0 - x0) * scale))
    dy0 = int(round((sy0 - y0) * scale))
    dw = max(int(round(crop.shape[1] * scale)), 1)
    dh = max(int(round(crop.shape[0] * scale)), 1)
    patch = np.asarray(
        Image.fromarray(crop).resize((dw, dh), Image.BILINEAR))
    dx1, dy1 = min(dx0 + dw, TILE), min(dy0 + dh, TILE)
    tile[dy0:dy1, dx0:dx1] = patch[: dy1 - dy0, : dx1 - dx0]
    return tile


def _png(arr: Optional[np.ndarray]) -> bytes:
    if arr is None:
        img = Image.new("LA", (TILE, TILE), (0, 0))  # transparent
    else:
        img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def tile(request, z: str, x: str, y: str) -> HttpResponse:
    try:
        shade = _shaded()
        arr = _tile_array(shade, int(z), int(x), int(y))
    except FileNotFoundError:
        arr = None  # serve blank until first erode run
    resp = HttpResponse(_png(arr), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=60"
    return resp
