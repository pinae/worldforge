"""
erosion.py -- GPU heightmap erosion for constrained procedural terrain.

Designed for a workflow where only sparse control points are authored
(fixed elevations, river cells, mountain peaks) and the simulation must
fill in geologically plausible detail around them.

Two complementary models, run in sequence:

1. StreamPowerErosion -- geological time scales. Fluvial incision via the
   stream power law  E = K * A^m * S^n  with multiple-flow-direction (MFD)
   drainage routing, Planchon-Darboux depression filling, downstream
   sediment routing with deposition (in the spirit of Yuan et al. 2019),
   hillslope diffusion, thermal erosion (talus-angle landslides) and an
   optional tectonic uplift field.
   Refs: Cordonnier et al., EG 2016; Braun & Willett, Geomorphology 2013;
         Tzathas et al., CGF 2024.
   -> This carves the realistic dendritic valley / ridge structure.

2. PipeModelErosion -- short time scales, detail pass. The virtual-pipes
   shallow water model of Mei, Decaudin & Hu 2007 ("Fast Hydraulic Erosion
   Simulation and Visualization on GPU"): explicit water depth, pipe
   fluxes, velocity-driven sediment capacity, semi-Lagrangian sediment
   advection, evaporation.
   -> This adds gullies, alluvial fans and fine channel texture.

All state lives in (H, W) float32 tensors; every step is a handful of
vectorised tensor ops, so the same code runs on CPU and CUDA.

Conventions
-----------
z      terrain elevation [m]
dx     cell size [m]
A      drainage area [m^2] (rainfall-weighted contributing area)
S      slope along steepest descent [-]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

import torch
import torch.nn.functional as F

# ----------------------------------------------------------------------------
# D8 neighbourhood helpers
# ----------------------------------------------------------------------------

# (dy, dx) offsets of the 8 neighbours and their distances in cell units.
_OFFSETS = [(-1, -1), (-1, 0), (-1, 1),
            (0, -1), (0, 1),
            (1, -1), (1, 0), (1, 1)]
_DIST = torch.tensor([2 ** 0.5, 1.0, 2 ** 0.5,
                      1.0, 1.0,
                      2 ** 0.5, 1.0, 2 ** 0.5])


def _shift(t: torch.Tensor, dy: int, dx: int) -> torch.Tensor:
    """Return s with s[y, x] = t[y - dy, x - dx], edge-replicated.

    I.e. the value each cell "sees" coming from its neighbour at offset
    (-dy, -dx); equivalently, t pushed in direction (dy, dx).
    """
    # F.pad expects NCHW; pad = (left, right, top, bottom)
    p = F.pad(t[None, None],
              (max(dx, 0), max(-dx, 0), max(dy, 0), max(-dy, 0)),
              mode="replicate")[0, 0]
    h, w = t.shape
    y0 = max(-dy, 0)
    x0 = max(-dx, 0)
    return p[y0:y0 + h, x0:x0 + w]


def _neighbor_stack(z: torch.Tensor) -> torch.Tensor:
    """(8, H, W) stack of neighbour elevations z[y+dy, x+dx]."""
    return torch.stack([_shift(z, -dy, -dx) for dy, dx in _OFFSETS])


# ----------------------------------------------------------------------------
# Flow routing
# ----------------------------------------------------------------------------

def fill_depressions(z: torch.Tensor, eps: float = 1e-3,
                     max_iters: int = 1000) -> torch.Tensor:
    """Planchon & Darboux (2002) depression filling, fully parallel.

    Start from +inf everywhere except the open boundary, then repeatedly
    lower each cell to max(z, min(neighbour) + eps).  Converges to the
    filled DEM in O(longest-flow-path) iterations.  Guarantees that MFD
    routing below never gets stuck in a pit (water exits every lake).
    """
    big = z.max() + 1e4
    zf = torch.full_like(z, big)
    zf[0, :] = z[0, :]
    zf[-1, :] = z[-1, :]
    zf[:, 0] = z[:, 0]
    zf[:, -1] = z[:, -1]
    eps_t = eps * _DIST.to(z.device).view(8, 1, 1)
    for _ in range(max_iters):
        nmin = (_neighbor_stack(zf) + eps_t).min(dim=0).values
        new = torch.maximum(z, torch.minimum(zf, nmin))
        if torch.allclose(new, zf):
            zf = new
            break
        zf = new
    return zf


def flow_weights(z: torch.Tensor, dx: float, p: float = 1.3) -> torch.Tensor:
    """(8, H, W) MFD partition: fraction of each cell's outflow sent to
    each lower neighbour, weighted by slope^p (Freeman 1991).

    p -> infinity approaches D8 (single steepest receiver, sharper
    channels); p ~ 1 gives smoother, more diffuse drainage.
    """
    dist = (_DIST.to(z.device) * dx).view(8, 1, 1)
    drop = (z[None] - _neighbor_stack(z)) / dist  # slope to each nbr
    w = drop.clamp_min(0.0) ** p
    total = w.sum(dim=0, keepdim=True)
    return torch.where(total > 0, w / total.clamp_min(1e-12),
                       torch.zeros_like(w))


def accumulate(source: torch.Tensor, w: torch.Tensor,
               iters: int = 256, tol: float = 1e-4) -> torch.Tensor:
    """Route `source` (e.g. rainfall * cell_area) downstream through the
    MFD weights and return the steady-state accumulated flux at each cell:

        Q = source + sum_k  push_k( Q * w_k )

    Solved by fixed-point iteration (Jacobi); each sweep advances flow by
    one cell, so `iters` should be >= the longest flow path in cells.
    On GPU each sweep is a few shifted adds, so 256 sweeps on a 1024^2
    grid is fast.  (For production-scale speedups see FastFlow, CGF 2024.)
    """
    q = source.clone()
    for _ in range(iters):
        inflow = torch.zeros_like(q)
        contrib = q[None] * w  # (8, H, W)
        for k, (dy, dx_) in enumerate(_OFFSETS):
            inflow += _shift(contrib[k], dy, dx_)
        new = source + inflow
        if torch.abs(new - q).max() < tol * source.mean().clamp_min(1e-12):
            return new
        q = new
    return q


def steepest_slope(z: torch.Tensor, dx: float) -> tuple[torch.Tensor,
torch.Tensor]:
    """Steepest-descent slope S (>= 0) and the receiver elevation."""
    dist = (_DIST.to(z.device) * dx).view(8, 1, 1)
    nbrs = _neighbor_stack(z)
    drop = (z[None] - nbrs) / dist
    s, idx = drop.max(dim=0)
    recv = nbrs.gather(0, idx[None])[0]
    return s.clamp_min(0.0), recv


# ----------------------------------------------------------------------------
# User constraints (the app's sparse control points)
# ----------------------------------------------------------------------------

@dataclass
class Constraints:
    """Sparse authoring data, re-imposed after every simulation step.

    fixed_mask / fixed_z : cells whose elevation is pinned exactly
                           (surveyed points of real places, authored spots).
    river_mask           : cells that must carry a river.  Implemented by
                           injecting extra rainfall there, so the stream
                           power law carves a real valley around the
                           authored course instead of a pasted-on trench.
    peak_mask            : cells that must remain local maxima; protected
                           from fluvial incision and gently uplifted if a
                           neighbour overtakes them.
    """
    fixed_mask: Optional[torch.Tensor] = None  # bool (H, W)
    fixed_z: Optional[torch.Tensor] = None  # float (H, W)
    river_mask: Optional[torch.Tensor] = None  # bool (H, W)
    peak_mask: Optional[torch.Tensor] = None  # bool (H, W)
    river_rain_boost: float = 50.0  # extra rain on river cells

    def rainfall(self, base: torch.Tensor) -> torch.Tensor:
        if self.river_mask is None:
            return base
        return base + base.mean() * self.river_rain_boost * self.river_mask

    def apply(self, z: torch.Tensor) -> torch.Tensor:
        if self.peak_mask is not None:
            # keep authored peaks strictly above their neighbourhood
            nmax = _neighbor_stack(z).max(dim=0).values
            z = torch.where(self.peak_mask, torch.maximum(z, nmax + 1.0), z)
        if self.fixed_mask is not None and self.fixed_z is not None:
            z = torch.where(self.fixed_mask, self.fixed_z, z)
        return z


# ----------------------------------------------------------------------------
# Model 1: long-term fluvial erosion (stream power law)
# ----------------------------------------------------------------------------

@dataclass
class StreamPowerParams:
    dx: float = 100.0  # cell size [m]
    dt: float = 1000.0  # time step [years]
    k_spl: float = 2e-5  # erodibility K  [yr^-1 m^(1-2m)]
    m: float = 0.5  # area exponent   (m/n ~ 0.5 is empirical)
    n: float = 1.0  # slope exponent
    g_dep: float = 1.0  # deposition coefficient G (Yuan et al. 2019);
    # 0 = detachment-limited (pure incision)
    k_diff: float = 0.1  # hillslope diffusion [m^2/yr]; low values
    # keep ridgecrests sharp, high values round them
    recv_clamp: float = 0.5  # max fraction of drop-to-receiver eroded
    # per step (1.0 = old hard clamp)
    talus: float = 0.7  # tan(repose angle) for thermal erosion (~35 deg)
    k_thermal: float = 0.5  # fraction of talus excess moved per step
    uplift: float = 0.0  # uniform uplift [m/yr]; or pass a field below
    mfd_p: float = 1.3  # MFD slope exponent
    rain: float = 1.0  # precipitation [m/yr] (relative units are fine)
    accum_iters: int = 256


class StreamPowerErosion:
    """Carves drainage networks at geological time scales.

    Per step:
      1. fill depressions so every cell drains to the boundary
      2. MFD flow routing -> drainage area A
      3. detachment:  E = K A^m S^n  (explicit, clamped so a cell never
         cuts below its steepest receiver -- the stability trick that makes
         the explicit scheme behave like Braun & Willett's implicit one)
      4. route eroded sediment downstream; deposit  D = G * Qs / A
         (capacity shrinks where A is small or slope flattens -> fans,
         floodplains, valley fill)
      5. hillslope diffusion + thermal erosion + uplift
      6. re-impose user constraints
    """

    def __init__(self, params: StreamPowerParams,
                 uplift_field: Optional[torch.Tensor] = None):
        self.p = params
        self.uplift_field = uplift_field

    def step(self, z: torch.Tensor,
             constraints: Optional[Constraints] = None) -> torch.Tensor:
        p = self.p
        cell_area = p.dx * p.dx

        rain = torch.full_like(z, p.rain)
        if constraints is not None:
            rain = constraints.rainfall(rain)

        # 1-2. routing on the depression-filled surface
        zf = fill_depressions(z)
        w = flow_weights(zf, p.dx, p.mfd_p)
        area = accumulate(rain * cell_area, w, iters=p.accum_iters)

        # 3. stream power incision
        slope, recv = steepest_slope(zf, p.dx)
        e_rate = p.k_spl * area.pow(p.m) * slope.pow(p.n)  # [m/yr]
        if constraints is not None and constraints.peak_mask is not None:
            e_rate = e_rate * (~constraints.peak_mask)
        erode = torch.minimum(e_rate * p.dt,
                              p.recv_clamp * (z - recv).clamp_min(0.0))

        # 4. sediment routing & deposition (transport-limited component)
        deposit = torch.zeros_like(z)
        if p.g_dep > 0:
            qs = accumulate(erode * cell_area, w, iters=p.accum_iters)
            deposit = (p.g_dep * qs / area.clamp_min(cell_area))
            # never deposit above the lowest upstream neighbour: cap by a
            # fraction of local relief to keep the scheme stable
            relief = (_neighbor_stack(z).max(dim=0).values - z).clamp_min(0.0)
            deposit = torch.minimum(deposit, 0.25 * relief + 1e-3)

        z = z - erode + deposit

        # 5a. hillslope diffusion (soil creep): dz/dt = k_diff * laplacian(z)
        lap = (_shift(z, 0, 1) + _shift(z, 0, -1) +
               _shift(z, 1, 0) + _shift(z, -1, 0) - 4 * z) / (p.dx * p.dx)
        z = z + p.k_diff * lap * p.dt

        # 5b. thermal erosion: move material down any face steeper than the
        # angle of repose, split proportionally among offending neighbours
        dist = (_DIST.to(z.device) * p.dx).view(8, 1, 1)
        drop = z[None] - _neighbor_stack(z)
        excess = (drop - p.talus * dist).clamp_min(0.0)
        total = excess.sum(dim=0)
        move = p.k_thermal * 0.5 * total  # outgoing
        share = torch.where(total[None] > 0,
                            excess / total.clamp_min(1e-12),
                            torch.zeros_like(excess))
        outgoing = move[None] * share
        incoming = torch.zeros_like(z)
        for k, (dy, dx_) in enumerate(_OFFSETS):
            incoming += _shift(outgoing[k], dy, dx_)
        z = z - move + incoming

        # 5c. tectonic uplift
        if self.uplift_field is not None:
            z = z + self.uplift_field * p.dt
        elif p.uplift:
            z = z + p.uplift * p.dt

        # 6. constraints
        if constraints is not None:
            z = constraints.apply(z)
        return z


# ----------------------------------------------------------------------------
# Model 2: shallow-water virtual pipes (Mei, Decaudin & Hu 2007)
# ----------------------------------------------------------------------------

@dataclass
class PipeParams:
    dx: float = 100.0  # cell size [m]
    dt: float = 0.02  # time step [s-ish, dimensionless in practice]
    gravity: float = 9.81
    pipe_area: float = 20.0  # virtual pipe cross-section A_pipe
    rain_rate: float = 0.012  # water added per step
    evaporation: float = 0.015
    capacity_k: float = 1.0  # sediment capacity constant Kc
    erode_k: float = 0.5  # dissolving constant Ks
    deposit_k: float = 0.5  # deposition constant Kd
    min_tilt: float = 0.005  # lower bound on sin(alpha): keeps flat areas
    # from having zero capacity (avoids artifacts)
    max_erosion_depth: float = 0.4  # limit per-step bite into bedrock


class PipeModelErosion:
    """Fine-scale hydraulic erosion with explicit water (4-neighbour pipes).

    State: water depth d, suspended sediment s, pipe fluxes f (4, H, W)
    in order [left, right, top, bottom].

    Per step (Mei et al. 2007, Sec. 3):
      1. rain increment            d += r * dt
      2. flux update               f_i = max(0, f_i + dt A g dh_i / l),
         scaled so total outflow <= available water
      3. water surface update from flux divergence
      4. velocity field from net horizontal fluxes
      5. capacity C = Kc * sin(alpha) * |v|;  erode if C > s else deposit
      6. semi-Lagrangian advection of suspended sediment
      7. evaporation
    """

    def __init__(self, params: PipeParams):
        self.p = params

    def init_state(self, z: torch.Tensor) -> dict[str, torch.Tensor]:
        return {
            "d": torch.zeros_like(z),  # water depth
            "s": torch.zeros_like(z),  # suspended sediment
            "f": torch.zeros(4, *z.shape, device=z.device),  # L R T B fluxes
        }

    def step(self, z: torch.Tensor, state: dict[str, torch.Tensor],
             constraints: Optional[Constraints] = None
             ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        p = self.p
        d, s, f = state["d"], state["s"], state["f"]
        l = p.dx

        # 1. rain (boosted on authored river cells -> they stay wet)
        rain = torch.full_like(z, p.rain_rate)
        if constraints is not None:
            rain = constraints.rainfall(rain)
        d = d + rain * p.dt

        # 2. outflow flux through the 4 pipes
        h = z + d  # water surface
        dh = torch.stack([h - _shift(h, 0, -1),  # to left  neighbour
                          h - _shift(h, 0, 1),  # to right
                          h - _shift(h, -1, 0),  # to top
                          h - _shift(h, 1, 0)])  # to bottom
        f = (f + p.dt * p.pipe_area * p.gravity * dh / l).clamp_min(0.0)
        # closed domain: no flux through the outer walls
        f[0][:, 0] = 0;
        f[1][:, -1] = 0;
        f[2][0, :] = 0;
        f[3][-1, :] = 0
        # scale so we never drain more water than the column holds
        out = f.sum(dim=0)
        k = torch.where(out > 0,
                        (d * l * l / (out * p.dt + 1e-12)).clamp_max(1.0),
                        torch.ones_like(out))
        f = f * k[None]

        # 3. water depth update: inflow - outflow
        inflow = (_shift(f[1], 0, -1) + _shift(f[0], 0, 1) +
                  _shift(f[3], -1, 0) + _shift(f[2], 1, 0))
        dv = p.dt * (inflow - out) / (l * l)
        d2 = (d + dv).clamp_min(0.0)

        # 4. velocity from average net flux (du: x direction, dv_: y)
        wx = 0.5 * (_shift(f[1], 0, 1) - f[0] + f[1] - _shift(f[0], 0, -1))
        wy = 0.5 * (_shift(f[3], 1, 0) - f[2] + f[3] - _shift(f[2], -1, 0))
        dmean = 0.5 * (d + d2)
        u = wx / (l * dmean.clamp_min(1e-3))
        v = wy / (l * dmean.clamp_min(1e-3))
        speed = torch.sqrt(u * u + v * v)

        # 5. erosion / deposition
        gx = (_shift(z, 0, 1) - _shift(z, 0, -1)) / (2 * l)
        gy = (_shift(z, 1, 0) - _shift(z, -1, 0)) / (2 * l)
        sin_a = torch.sqrt(gx * gx + gy * gy) / torch.sqrt(
            1 + gx * gx + gy * gy)
        cap = p.capacity_k * sin_a.clamp_min(p.min_tilt) * speed
        # shallow-water damping: thin films shouldn't carve like rivers
        cap = cap * (d2 / (d2 + 0.05)).clamp(0.0, 1.0)

        erode = (p.erode_k * (cap - s)).clamp(min=0.0,
                                              max=p.max_erosion_depth)
        deposit = (p.deposit_k * (s - cap)).clamp_min(0.0)
        if constraints is not None and constraints.peak_mask is not None:
            erode = erode * (~constraints.peak_mask)
        z = z - erode + deposit
        s = s + erode - deposit

        # 6. semi-Lagrangian advection of suspended sediment
        H, W = z.shape
        ys, xs = torch.meshgrid(
            torch.arange(H, device=z.device, dtype=z.dtype),
            torch.arange(W, device=z.device, dtype=z.dtype), indexing="ij")
        src_x = xs - u * p.dt / l
        src_y = ys - v * p.dt / l
        grid = torch.stack([2 * src_x / (W - 1) - 1,
                            2 * src_y / (H - 1) - 1], dim=-1)[None]
        s = F.grid_sample(s[None, None], grid, mode="bilinear",
                          padding_mode="border", align_corners=True)[0, 0]

        # 7. evaporation
        d2 = d2 * max(0.0, 1.0 - p.evaporation * p.dt)

        if constraints is not None:
            z = constraints.apply(z)
        return z, {"d": d2, "s": s, "f": f}


# ----------------------------------------------------------------------------
# Driver: the two-phase pipeline the Django task calls
# ----------------------------------------------------------------------------

@dataclass
class ErosionConfig:
    spl_steps: int = 120
    pipe_steps: int = 400
    spl: StreamPowerParams = field(default_factory=StreamPowerParams)
    pipe: PipeParams = field(default_factory=PipeParams)


def erode(z: torch.Tensor,
          config: ErosionConfig = ErosionConfig(),
          constraints: Optional[Constraints] = None,
          uplift_field: Optional[torch.Tensor] = None,
          progress: Optional[Callable[[str, int, int, torch.Tensor],
          None]] = None) -> torch.Tensor:
    """Full pipeline: macro fluvial carving, then micro hydraulic detail.

    `progress(phase, step, total, z)` is called every few steps -- wire it
    to a Django Channels group_send to stream preview frames to React.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    z = z.to(device=device, dtype=torch.float32).clone()
    if constraints is not None:
        for name in ("fixed_mask", "fixed_z", "river_mask", "peak_mask"):
            t = getattr(constraints, name)
            if t is not None:
                setattr(constraints, name, t.to(device))
    if uplift_field is not None:
        uplift_field = uplift_field.to(device, torch.float32)

    spl = StreamPowerErosion(config.spl, uplift_field)
    for i in range(config.spl_steps):
        z = spl.step(z, constraints)
        if progress and i % 5 == 0:
            progress("stream_power", i, config.spl_steps, z)

    pipe = PipeModelErosion(config.pipe)
    state = pipe.init_state(z)
    for i in range(config.pipe_steps):
        z, state = pipe.step(z, state, constraints)
        if progress and i % 20 == 0:
            progress("pipe_model", i, config.pipe_steps, z)

    return z.cpu()


def water_map(z: torch.Tensor, dx: float = 100.0,
              threshold_quantile: float = 0.98) -> torch.Tensor:
    """Convenience: boolean river mask from drainage area, for rendering
    rivers in the frontend after the simulation."""
    zf = fill_depressions(z)
    w = flow_weights(zf, dx)
    area = accumulate(torch.full_like(z, dx * dx), w)
    return area > torch.quantile(area.flatten(), threshold_quantile)
