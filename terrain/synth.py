"""
synth.py -- synthetic starting terrains (pure PyTorch, no noise deps).

fBm built by summing bicubically-upsampled random grids. Good enough as
erosion input; the simulation supplies the realism.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


def fbm(size: int, octaves: int = 8, seed: int = 0,
        persistence: float = 0.5, lacunarity: float = 2.0,
        ridged: bool = False) -> torch.Tensor:
    """(size, size) fractal noise in [0, 1].

    ridged=True turns each octave into 1 - |2x - 1| -> sharp crest lines,
    a much better starting point for mountain ranges than plain fBm.
    """
    gen = torch.Generator().manual_seed(seed)
    out = torch.zeros(size, size)
    amp, total, res = 1.0, 0.0, 4
    for _ in range(octaves):
        grid = torch.rand(1, 1, res + 1, res + 1, generator=gen)
        layer = F.interpolate(grid, size=(size, size),
                              mode="bicubic", align_corners=True)[0, 0]
        if ridged:
            layer = 1.0 - (2.0 * layer - 1.0).abs()
        out = out + amp * layer
        total += amp
        amp *= persistence
        res = min(int(res * lacunarity), size)
    out = out / total
    return (out - out.min()) / (out.max() - out.min() + 1e-12)


def edge_falloff(size: int, margin: float = 0.25) -> torch.Tensor:
    """Smooth mask that lowers terrain toward the borders so all drainage
    can exit the domain (the depression filler treats the boundary as the
    outlet).  margin = fraction of the half-width over which to fade."""
    ax = torch.linspace(-1.0, 1.0, size)
    yy, xx = torch.meshgrid(ax, ax, indexing="ij")
    d = torch.maximum(yy.abs(), xx.abs())               # square distance
    t = ((1.0 - d) / margin).clamp(0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)                      # smoothstep


def demo_terrain(size: int = 512, seed: int = 0,
                 relief: float = 1500.0) -> torch.Tensor:
    """Plausible starting heightmap [m]: ridged mountains + rolling base,
    faded at the borders so rivers have somewhere to go."""
    mountains = fbm(size, seed=seed, ridged=True) ** 1.5
    base = fbm(size, seed=seed + 1, octaves=5)
    z = 0.75 * mountains + 0.25 * base
    return relief * z * edge_falloff(size)
