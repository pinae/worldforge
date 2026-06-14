"""
manage.py tiletest -- exercise the tile pyramid without a browser.

Renders every tile Leaflet would request across a range of zoom levels and
writes them into a contact sheet per zoom, plus prints the coordinate range.
This isolates the tile MATH from Leaflet, HTTP, CORS and the proxy.

    uv run python manage.py tiletest
    uv run python manage.py tiletest --zooms -2 -1 0 1

If the contact sheets look like correct slices of your terrain, the tile
view is fine and the bug is in Leaflet wiring. If they're wrong/blank, the
bug is here in the tile math.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand
from PIL import Image


class Command(BaseCommand):
    help = "Render tiles to disk to debug the pyramid without a browser."

    def add_arguments(self, parser):
        parser.add_argument("--zooms", type=int, nargs="+",
                            default=[-2, -1, 0, 1])
        parser.add_argument("--out", default="runs/tiletest")

    def handle(self, *args, **opt):
        from django.conf import settings
        from terrain.tiles import _shaded, _tile_array, TILE

        # force the cache to load so failures surface clearly
        try:
            shade = _shaded()
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"_shaded() failed: {e}"))
            self.stderr.write("Is WORLDFORGE_HEIGHTMAP set and the .npy present?")
            return
        n = shade.shape[0]
        self.stdout.write(f"heightmap: {n}x{n} px")

        out = Path(opt["out"])
        out.mkdir(parents=True, exist_ok=True)

        for z in opt["zooms"]:
            # how many tiles cover the map at this zoom, and which indices
            scale = 2.0 ** z  # map-units -> on-screen px factor
            span = TILE / scale  # heightmap px per tile
            ntiles = max(int(np.ceil(n / span)), 1)
            self.stdout.write(
                f"z={z:>3}: span={span:8.1f} px/tile, "
                f"expect x,y in [0,{ntiles - 1}]")

            cols = []
            for ty in range(ntiles):
                row = []
                for tx in range(ntiles):
                    arr = _tile_array(shade, z, tx, ty)
                    row.append(arr if arr is not None
                               else np.zeros((TILE, TILE), np.uint8))
                cols.append(np.concatenate(row, axis=1))
            sheet = np.concatenate(cols, axis=0)
            path = out / f"z{z}.png"
            Image.fromarray(sheet).save(path)
            self.stdout.write(self.style.SUCCESS(f"  wrote {path}"))

        self.stdout.write("\nIf these sheets show terrain, the math is good.")
