"""
manage.py erode -- run the erosion pipeline on a synthetic terrain and
write diagnostics for parameter tuning.

Examples
--------
uv run python manage.py erode
uv run python manage.py erode --size 512 --seed 3 --spl-steps 150
uv run python manage.py erode --k-spl 5e-5 --g-dep 0.5 --out runs/k5e5
uv run python manage.py erode --pipe-steps 0          # phase 1 only
uv run python manage.py erode --frames --every 5      # dump preview frames

Outputs in --out (default runs/<timestamp>):
  triptych_initial.png   hillshade | log drainage | rivers  (before)
  triptych_final.png     same, after erosion
  final.npy              eroded heightmap (float32, metres)
  params.json            full parameter record for reproducibility
  frames/                hillshade PNGs per N steps (with --frames)

This command is deliberately a thin wrapper: terrain comes from
terrain.synth, execution goes through terrain.sinks.run_erosion (the same
entry point the Celery task will use), rendering through terrain.viz.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import torch
from django.core.management.base import BaseCommand

from terrain.erosion import ErosionConfig, PipeParams, StreamPowerParams
from terrain.sinks import DiskFrameSink, run_erosion
from terrain.synth import demo_terrain
from terrain.viz import triptych


class Command(BaseCommand):
    help = "Erode a synthetic terrain and write diagnostic figures."

    def add_arguments(self, parser):
        g = parser.add_argument_group("terrain")
        g.add_argument("--size", type=int, default=512)
        g.add_argument("--seed", type=int, default=0)
        g.add_argument("--relief", type=float, default=1500.0,
                       help="initial max elevation [m]")
        g.add_argument("--dx", type=float, default=100.0,
                       help="cell size [m]")

        g = parser.add_argument_group("stream power phase")
        g.add_argument("--spl-steps", type=int, default=120)
        g.add_argument("--k-spl", type=float, default=2e-5)
        g.add_argument("--dt", type=float, default=1000.0)
        g.add_argument("--g-dep", type=float, default=1.0)
        g.add_argument("--uplift", type=float, default=0.0)
        g.add_argument("--accum-iters", type=int, default=256)

        g = parser.add_argument_group("pipe model phase")
        g.add_argument("--pipe-steps", type=int, default=400)

        g = parser.add_argument_group("output")
        g.add_argument("--out", type=str, default=None,
                       help="output dir (default runs/<timestamp>)")
        g.add_argument("--frames", action="store_true",
                       help="dump hillshade preview frames")
        g.add_argument("--every", type=int, default=10,
                       help="frame interval in steps")

    def handle(self, *args, **opt):
        out = Path(opt["out"] or f"runs/{time.strftime('%Y%m%d-%H%M%S')}")
        out.mkdir(parents=True, exist_ok=True)

        config = ErosionConfig(
            spl_steps=opt["spl_steps"],
            pipe_steps=opt["pipe_steps"],
            spl=StreamPowerParams(
                dx=opt["dx"], dt=opt["dt"], k_spl=opt["k_spl"],
                g_dep=opt["g_dep"], uplift=opt["uplift"],
                accum_iters=opt["accum_iters"],
            ),
            pipe=PipeParams(dx=opt["dx"]),
        )

        (out / "params.json").write_text(json.dumps({
            "terrain": {k: opt[k] for k in
                        ("size", "seed", "relief", "dx")},
            "config": dataclasses.asdict(config),
        }, indent=2))

        self.stdout.write(f"device: "
                          f"{'cuda' if torch.cuda.is_available() else 'cpu'}")
        self.stdout.write("generating starting terrain...")
        z0 = demo_terrain(opt["size"], opt["seed"], opt["relief"])
        triptych(z0, opt["dx"], str(out / "triptych_initial.png"),
                 title="initial", accum_iters=opt["accum_iters"])

        sinks = ()
        if opt["frames"]:
            sinks = (DiskFrameSink(out / "frames", dx=opt["dx"],
                                   every=opt["every"]),)

        self.stdout.write(f"eroding: {config.spl_steps} stream-power steps, "
                          f"{config.pipe_steps} pipe steps...")
        t0 = time.time()
        z = run_erosion(z0, config, sinks=sinks)
        self.stdout.write(f"done in {time.time() - t0:.1f}s")

        np.save(out / "final.npy", z.numpy().astype(np.float32))
        fig = triptych(z, opt["dx"], str(out / "triptych_final.png"),
                       title="eroded", accum_iters=opt["accum_iters"])
        self.stdout.write(self.style.SUCCESS(f"figure: {fig}"))
        self.stdout.write(self.style.SUCCESS(f"outputs in: {out}/"))
