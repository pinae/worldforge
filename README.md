# WorldForge — Constraint-Driven Terrain Generation

Create realistic maps of fictional worlds — and plausible reconstructions of
real places — from **sparse control points**. The user only pins down a few
things: "this point is at 1,200 m", "a river runs through here", "this is a
mountain peak". Physically-based erosion simulation fills in everything else
with geologically consistent detail: dendritic river networks, watersheds,
ridgelines, valleys, alluvial fans.

## Core idea

Classical terrain tools force a choice: procedural noise (fast, controllable,
but geologically meaningless) or erosion simulation (realistic, but hard to
steer). We treat the user's sparse annotations as **constraints on a
simulation**:

- **Fixed elevations** are re-imposed after every simulation step, so the
  terrain relaxes around them.
- **Authored rivers** are not stamped into the heightmap. Instead, river
  cells receive a rainfall boost, so the stream power law *carves a genuine
  valley* around the authored course — banks, tributaries and floodplain
  included.
- **Peaks** are shielded from fluvial incision and kept locally maximal.

The result is a terrain that honours the author's intent but looks like it
has a hydrological and tectonic history.

## Architecture

| Layer | Tech | Role |
|---|---|---|
| Simulation | PyTorch | All heavy math as vectorised tensor ops, CPU/CUDA |
| Backend | Django + DRF | Projects, heightmaps, constraint storage, REST API |
| Jobs | Celery + Redis | Long-running erosion runs outside the request cycle |
| Live updates | Django Channels (WebSockets) | Stream preview frames to the client during a run |
| Frontend | React (Vite) + canvas / three.js | Interactive map editing and 2D/3D display |
| Packaging | uv | Python dependency and environment management |

The simulation driver (`terrain/erosion.py: erode()`) exposes a
`progress(phase, step, total, z)` callback. The same callback seam serves
both development (management command writing PNG frames to disk) and
production (Celery task pushing frames over a Channels group).

## Erosion pipeline

Two complementary models run in sequence (`terrain/erosion.py`):

### Phase 1 — Stream power law (macro structure)

Geological-timescale fluvial erosion. Per step:

1. **Depression filling** — parallel Planchon–Darboux sweep so every cell
   drains to the boundary.
2. **Flow routing** — multiple-flow-direction (Freeman-style, slope^p
   weighted) accumulation of rainfall → drainage area *A*.
3. **Fluvial incision** — stream power law *E = K·Aᵐ·Sⁿ*, clamped so a cell
   never cuts below its steepest receiver (stability trick echoing Braun &
   Willett's implicit scheme).
4. **Sediment routing & deposition** — eroded material is routed downstream
   and redeposited with a G-factor (after Yuan et al. 2019) → floodplains
   and fans, not just incision.
5. **Hillslope processes** — linear diffusion (soil creep) and thermal
   erosion (talus-angle landslides).
6. **Tectonic uplift** — uniform or as a user-paintable field
   (Cordonnier et al. 2016).
7. **Constraint re-projection.**

### Phase 2 — Virtual pipes shallow water (micro detail)

Short-timescale hydraulic erosion after Mei, Decaudin & Hu 2007: explicit
water depth per cell, flux through four virtual pipes, velocity-derived
sediment capacity *C = K_c·sin α·|v|*, erosion/deposition against capacity,
semi-Lagrangian sediment advection, evaporation. Adds gullies, channel
texture and fans on top of the phase-1 macrostructure.

### Utilities

- `water_map()` — extracts a river mask from drainage area for rendering.
- `Constraints` — dataclass holding fixed/river/peak masks, applied each step.

## Parameter guide

All parameters are exposed on `manage.py erode`. The mental model: the
terrain you get is the **balance of four competing processes** — uplift
(builds relief), fluvial incision (carves valleys), diffusion (rounds
everything), thermal erosion (caps slope angles). Tuning means shifting
that balance, not searching for one magic number.

### Terrain & discretisation

| Flag | Default | Meaning |
|---|---|---|
| `--size` | 512 | Grid resolution. Runtime grows ~quadratically; tune at 256–512, render at 1024+. |
| `--seed` | 0 | Noise seed. **Fix it while tuning** so changes you see come from parameters, not luck. |
| `--relief` | 1500 | Initial max elevation [m]. Mostly matters relative to `dx`: relief/dx sets initial slopes. |
| `--dx` | 100 | Cell size [m]. Physical constants below are calibrated against it; if you change `dx`, expect to retune `k-spl` and `k-diff`. |

### Time stepping

| Flag | Default | Meaning |
|---|---|---|
| `--dt` | 1000 | Years per step. Smaller = more accurate, slower. If results look "shattered" (single-cell canyons), `dt` is too large: the per-step incision `K·Aᵐ·Sⁿ·dt` exceeds local relief and the receiver clamp takes over. Rule of thumb: big rivers should erode ≪ their bank height per step. 200 is a safe tuning value. |
| `--spl-steps` | 120 | Number of stream-power steps. Total simulated time = `dt · spl-steps`. With uplift > 0, run long enough to approach uplift/erosion equilibrium (watch when the figure stops changing between runs). |
| `--recv-clamp` | 0.5 | Max fraction of the drop to the downstream neighbour a cell may erode per step. Pure stability guard — if it visibly shapes the terrain (slot canyons), lower `dt` instead. |

### Fluvial erosion (the main character)

| Flag | Default | Meaning |
|---|---|---|
| `--k-spl` | 2e-5 | Erodibility K in *E = K·Aᵐ·Sⁿ*. The overall speed of valley carving. Think of it as rock softness: granite low, mudstone high. Sweep in factors of ~3. |
| `--uplift` | 0.0 | Tectonic uplift [m/yr]. **The realism switch.** 0 = decaying dead landscape; 0.001–0.003 (real orogen rates) = mountain range in equilibrium, with concave river profiles and self-renewing relief. Most "real-looking" runs have uplift on. |
| `--g-dep` | 1.0 | Deposition coefficient G (Yuan et al. 2019). 0 = pure incision (detachment-limited, high-energy mountain look). Higher values fill valley floors → floodplains, fans, gentler basins. |
| `--mfd-p` | 1.3 | Flow-concentration exponent of the multiple-flow-direction routing. ~1 = diffuse flow, soft broad valleys; 2–3 = flow funnels into fewer, stronger channels → sharper valley/ridge contrast, more alpine. ∞ would be classic D8. |
| `--accum-iters` | 256 | Sweeps of the flow-accumulation solver. Must exceed the longest river length **in cells**, or distal drainage area (and thus big-river erosion) is silently underestimated. Raise for `--size` > ~1024 or very elongated basins. |

### Hillslope processes (ridge character)

| Flag | Default | Meaning |
|---|---|---|
| `--k-diff` | 0.1 | Linear diffusion [m²/yr] (soil creep). Acts strongest at high curvature — i.e. ridgecrests. **The ridge-sharpness dial:** 0.02–0.1 keeps crests crisp (rocky/alpine), 0.3–1.0 gives rounded, soil-mantled hills (old, humid landscapes). Stability requires `k_diff·dt/dx² < 0.25`. |
| `--talus` | 0.7 | tan of the angle of repose (0.7 ≈ 35°). Thermal erosion flattens anything steeper to this angle, producing planar slopes; where two meet you get a sharp crest. Raise to 0.8–0.9 for jagged high-mountain ridges, lower to ~0.4 for crumbly badlands. |
| `--k-thermal` | 0.5 | Fraction of the over-talus excess moved per step. Relaxation speed, not the angle itself; rarely needs touching. |

### Detail pass (virtual pipes)

| Flag | Default | Meaning |
|---|---|---|
| `--pipe-steps` | 400 | Shallow-water erosion steps after phase 1. **Set to 0 while tuning phase 1** — judge one model at a time. Turn back on at the end for gullies and fine channel texture. Finer knobs (capacity, evaporation, pipe area) live in `PipeParams` in `terrain/erosion.py`. |

### Recipes

```bash
# Alpine range in uplift/erosion equilibrium: sharp ridges, deep valleys
uv run python manage.py erode --seed 3 --dt 200 --spl-steps 600 \
  --uplift 0.002 --k-diff 0.05 --talus 0.85 --mfd-p 2.0 --pipe-steps 0

# Old, gentle hill country: rounded crests, broad filled valleys
uv run python manage.py erode --seed 3 --dt 500 --spl-steps 400 \
  --uplift 0.0005 --k-diff 0.6 --g-dep 1.5 --mfd-p 1.1 --pipe-steps 0

# Badlands / heavily gullied
uv run python manage.py erode --seed 3 --dt 200 --spl-steps 300 \
  --k-spl 6e-5 --talus 0.4 --k-diff 0.05 --pipe-steps 600
```

How to read the output figure (`triptych_*.png`): left = "does it look
like terrain?" (hillshade); middle = "is the drainage dendritic?" (log
drainage area — crisp branching trees good, blurry radial blobs bad);
right = where the renderer would draw rivers (area > 98th percentile).
Every run also writes `params.json`, so keep the runs of good-looking
seeds/parameter sets around as presets.



Primary sources the implementation is based on:

- G. Cordonnier, J. Braun, M.-P. Cani, B. Benes, E. Galin, A. Peytavie,
  E. Guérin. *Large Scale Terrain Generation from Tectonic Uplift and
  Fluvial Erosion.* Computer Graphics Forum 35(2), EUROGRAPHICS 2016.
  doi:10.1111/cgf.12820 — stream power law + uplift for terrain generation.
- J. Braun, S. D. Willett. *A very efficient O(n), implicit and parallel
  method to solve the stream power equation.* Geomorphology 180–181, 2013 —
  stable solver formulation our explicit clamp approximates.
- X. P. Yuan, J. Braun, L. Guerit, D. Rouby, G. Cordonnier. *A new efficient
  method to solve the stream power law model taking into account sediment
  deposition.* JGR Earth Surface 124(6), 2019 — the G-factor deposition term.
- X. Mei, P. Decaudin, B.-G. Hu. *Fast Hydraulic Erosion Simulation and
  Visualization on GPU.* Pacific Graphics 2007 — the virtual-pipes shallow
  water model (phase 2).
- O. Planchon, F. Darboux. *A fast, simple and versatile algorithm to fill
  the depressions of digital elevation models.* Catena 46, 2002 — parallel
  depression filling.
- J. Freeman. *Calculating catchment area with divergent flow based on a
  regular grid.* Computers & Geosciences 17, 1991 — MFD flow routing.

Acceleration / future work:

- P. Tzathas, B. Gailleton, P. Steer, G. Cordonnier. *Physically-based
  analytical erosion for fast terrain generation.* CGF 43, 2024.
  doi:10.1111/cgf.15033 — analytical stream-power solutions; erosion amount
  becomes a slider instead of an iterative simulation. Candidate for
  interactive editing in the UI.
- A. Jain, B. Kerbl, J. Gain, B. Finley, G. Cordonnier. *FastFlow: GPU
  Acceleration of Flow and Depression Routing for Landscape Simulation.*
  CGF 43(7), 2024 — replacement for the Jacobi flow-accumulation loop at
  large grid sizes.
- O. Št'ava, B. Benes, M. Brisbin, J. Křivánek. *Interactive Terrain
  Modeling Using Hydraulic Erosion.* SCA 2008 — interactive editing tools
  on top of pipe-model erosion.

## Getting started

```bash
# backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver

# frontend
cd frontend && npm install && npm run dev
```

GPU note: `uv add torch` installs the default PyPI wheel. For a specific
CUDA build, pin a PyTorch index in `pyproject.toml` via `[[tool.uv.index]]`
and `[tool.uv.sources]`.

## Roadmap

- [x] Erosion module (stream power law + virtual pipes) — `terrain/erosion.py`
- [ ] `manage.py erode` command: fBm starting terrain, CLI parameters,
      PNG frame dumps (hillshade + log drainage area + water mask) for
      fast parameter tuning
- [ ] Celery task wrapping `erode()` with a Channels `group_send` progress
      callback
- [ ] Minimal React canvas viewer fed by WebSocket frames
- [ ] Constraint editor (place fixed heights, draw rivers, set peaks)
- [ ] Real-world mode: import DEM tiles as the starting terrain / constraints
- [ ] 3D preview (three.js heightmap mesh)
- [ ] Analytical stream-power mode (Tzathas et al. 2024) for interactive
      "age" slider

## Status

Early prototype. The simulation code is written but not yet
execution-tested; expect a parameter-tuning phase. Key knobs:
`accum_iters` (must exceed the longest flow path in cells),
`k_spl · dt` (carving aggressiveness), and the pipe model's
`dt` / `pipe_area` pair (numerical stability of the water solver).