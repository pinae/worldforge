"""
sinks.py -- where preview frames go during a simulation run.

`erosion.erode()` exposes a `progress(phase, step, total, z)` callback.
Sinks are the pluggable receiving end of that seam:

  * DiskFrameSink     -> dev tooling (management command): PNGs in a run dir
  * ChannelsFrameSink -> production: same PNG bytes, base64'd over a
                         Django Channels group to the React canvas

`run_erosion()` fans one callback out to any number of sinks, so the Celery
task and the management command share the exact same code path and only
differ in which sinks they attach.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Optional, Protocol

import torch

from .erosion import Constraints, ErosionConfig, erode


class FrameSink(Protocol):
    def emit(self, phase: str, step: int, total: int,
             z: torch.Tensor) -> None: ...
    def close(self, z: torch.Tensor) -> None: ...


class DiskFrameSink:
    """Writes hillshade PNG frames + a meta.json manifest into run_dir."""

    def __init__(self, run_dir: str | Path, dx: float = 100.0,
                 every: int = 10, downsample: int = 2):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dx = dx
        self.every = every
        self.downsample = downsample
        self._frames: list[dict] = []
        self._t0 = time.time()

    def emit(self, phase: str, step: int, total: int,
             z: torch.Tensor) -> None:
        if step % self.every:
            return
        from .viz import frame_png
        name = f"{phase}_{step:05d}.png"
        (self.dir / name).write_bytes(
            frame_png(z, self.dx, self.downsample))
        self._frames.append({"phase": phase, "step": step, "total": total,
                             "file": name, "t": time.time() - self._t0})

    def close(self, z: torch.Tensor) -> None:
        (self.dir / "meta.json").write_text(
            json.dumps({"frames": self._frames}, indent=2))


class ChannelsFrameSink:
    """Pushes the same PNG payloads to a Channels group for the React
    canvas.  Usable as-is once Channels is configured; the consumer just
    forwards `payload` to the socket."""

    def __init__(self, group: str, dx: float = 100.0,
                 every: int = 10, downsample: int = 2):
        self.group = group
        self.dx = dx
        self.every = every
        self.downsample = downsample

    def emit(self, phase: str, step: int, total: int,
             z: torch.Tensor) -> None:
        if step % self.every:
            return
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        from .viz import frame_png
        png = frame_png(z, self.dx, self.downsample)
        async_to_sync(get_channel_layer().group_send)(self.group, {
            "type": "erosion.frame",
            "payload": {"phase": phase, "step": step, "total": total,
                        "png_b64": base64.b64encode(png).decode()},
        })

    def close(self, z: torch.Tensor) -> None:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        async_to_sync(get_channel_layer().group_send)(
            self.group, {"type": "erosion.done", "payload": {}})


def run_erosion(z: torch.Tensor,
                config: Optional[ErosionConfig] = None,
                constraints: Optional[Constraints] = None,
                uplift_field: Optional[torch.Tensor] = None,
                sinks: tuple[FrameSink, ...] = ()) -> torch.Tensor:
    """Single entry point used by BOTH `manage.py erode` and the Celery
    task -- they differ only in the sinks they pass."""
    config = config or ErosionConfig()

    def progress(phase: str, step: int, total: int, zt: torch.Tensor):
        for s in sinks:
            s.emit(phase, step, total, zt)

    z_out = erode(z, config, constraints, uplift_field, progress)
    for s in sinks:
        s.close(z_out)
    return z_out
