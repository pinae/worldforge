"""
viz.py -- rendering building blocks shared by the management command (disk
PNGs / matplotlib figure) and, later, the Celery/Channels pipeline
(PNG bytes pushed over WebSockets).

Everything takes torch tensors, computes gradients in torch (so it can run
on the GPU next to the simulation), and only converts to numpy/PIL at the
encoding boundary.
"""

from __future__ import annotations

import io
import math
from typing import Optional

import numpy as np
import torch

from .erosion import accumulate, fill_depressions, flow_weights


# ----------------------------------------------------------------------------
# Derived layers
# ----------------------------------------------------------------------------

def hillshade(z: torch.Tensor, dx: float = 100.0,
              azimuth_deg: float = 315.0,
              altitude_deg: float = 45.0) -> torch.Tensor:
    """Lambertian hillshade in [0, 1] -- the standard cartographic view."""
    gy, gx = torch.gradient(z, spacing=dx)
    az = math.radians(azimuth_deg)
    alt = math.radians(altitude_deg)
    # surface normal (-gx, -gy, 1) vs. light direction
    lx = math.cos(alt) * math.sin(az)
    ly = math.cos(alt) * math.cos(az)
    lz = math.sin(alt)
    norm = torch.sqrt(gx * gx + gy * gy + 1.0)
    shade = (-gx * lx - gy * ly + lz) / norm
    return shade.clamp(0.0, 1.0)


def drainage_area(z: torch.Tensor, dx: float = 100.0,
                  accum_iters: int = 256) -> torch.Tensor:
    """Drainage area [m^2] -- the single most diagnostic layer for judging
    whether the fluvial model behaves (should show crisp dendritic trees)."""
    zf = fill_depressions(z)
    w = flow_weights(zf, dx)
    return accumulate(torch.full_like(z, dx * dx), w, iters=accum_iters)


def water_mask_from_area(area: torch.Tensor,
                         quantile: float = 0.98) -> torch.Tensor:
    return area > torch.quantile(area.flatten(), quantile)


# ----------------------------------------------------------------------------
# Encoding (PNG bytes -- same payload for disk frames and WebSocket frames)
# ----------------------------------------------------------------------------

def _to_uint8(t: torch.Tensor, vmin: Optional[float] = None,
              vmax: Optional[float] = None) -> np.ndarray:
    a = t.detach().float().cpu().numpy()
    lo = a.min() if vmin is None else vmin
    hi = a.max() if vmax is None else vmax
    a = np.clip((a - lo) / (hi - lo + 1e-12), 0.0, 1.0)
    return (a * 255).astype(np.uint8)


def frame_png(z: torch.Tensor, dx: float = 100.0,
              downsample: int = 1) -> bytes:
    """Hillshade preview of the current terrain as PNG bytes.

    This is the unit of streaming: the DiskFrameSink writes it to a file,
    the future ChannelsFrameSink base64s it into a WebSocket message.
    """
    from PIL import Image  # local import keeps torch-only callers light
    if downsample > 1:
        z = z[::downsample, ::downsample]
    img = _to_uint8(hillshade(z, dx * downsample))
    buf = io.BytesIO()
    Image.fromarray(img, mode="L").save(buf, format="PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Diagnostic figure (matplotlib; dev-tooling only)
# ----------------------------------------------------------------------------

def triptych(z: torch.Tensor, dx: float = 100.0, path: str = "erode.png",
             title: str = "", accum_iters: int = 256) -> str:
    """Side-by-side: hillshade | log10 drainage area | rivers over shade.

    Reads left to right as: "does it look like terrain?", "did the fluvial
    model produce dendritic drainage?", "where would the renderer draw
    rivers?".
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shade = hillshade(z, dx).cpu().numpy()
    area = drainage_area(z, dx, accum_iters)
    log_area = torch.log10(area.clamp_min(1.0)).cpu().numpy()
    rivers = water_mask_from_area(area).cpu().numpy()

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5), constrained_layout=True)

    axes[0].imshow(shade, cmap="gray")
    axes[0].set_title("hillshade")

    im = axes[1].imshow(log_area, cmap="viridis")
    axes[1].set_title("log10 drainage area [m$^2$]")
    fig.colorbar(im, ax=axes[1], fraction=0.046)

    overlay = np.stack([shade, shade, shade], axis=-1)
    overlay[rivers] = (0.1, 0.35, 0.9)
    axes[2].imshow(overlay)
    axes[2].set_title("rivers (area > q98) over hillshade")

    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    if title:
        fig.suptitle(title)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
