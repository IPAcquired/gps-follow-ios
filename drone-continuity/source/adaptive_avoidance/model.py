"""Executable oracle for the per-obstacle ArduCopter firmware patch."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Config:
    reaction_time: float = 0.35
    extra_cap: float = 1.0
    low_height_add: float = 0.15
    low_height_on: float = 1.5
    low_height_off: float = 1.8
    hysteresis: float = 0.05
    decay_rate: float = 0.5
    max_decay_dt: float = 10.0


@dataclass
class SectorState:
    extra: float = 0.0
    low_height: bool = False


def finite_clamp(value, default, lower, upper):
    value = value if isfinite(value) else default
    return min(max(value, lower), upper)


def update_obstacle(*, base, actual_body_xy, obstacle_unit_xy, horizontal=True,
                    velocity_valid=True, hagl=None, dt=0.1, enabled=False,
                    state=None, cfg=Config()):
    """Return (effective_margin, closing_speed, status, updated_state)."""
    state = state or SectorState()
    if not enabled or not horizontal:
        return base, 0.0, "stock", state
    reaction_time = finite_clamp(cfg.reaction_time, 0.35, 0.0, 1.0)
    extra_cap = finite_clamp(cfg.extra_cap, 1.0, 0.0, 2.0)
    low_height_add = finite_clamp(cfg.low_height_add, 0.15, 0.0, 0.5)
    low_height_on = finite_clamp(cfg.low_height_on, 1.5, 0.2, 10.0)
    low_height_off = max(low_height_on, finite_clamp(cfg.low_height_off, 1.8, 0.2, 10.0))
    if not velocity_valid or any(not isfinite(v) for v in actual_body_xy):
        raw_extra = extra_cap
        closing = 0.0
        status = "velocity-fallback"
    else:
        closing = max(0.0, sum(a * b for a, b in zip(actual_body_xy, obstacle_unit_xy)))
        raw_extra = min(closing * reaction_time, extra_cap)
        status = "active"
    if raw_extra > state.extra + cfg.hysteresis:
        state.extra = raw_extra
    elif raw_extra < state.extra - cfg.hysteresis:
        state.extra = max(raw_extra, state.extra - cfg.decay_rate * min(max(dt, 0.0), cfg.max_decay_dt))
    if hagl is not None and isfinite(hagl) and hagl >= 0:
        if state.low_height:
            state.low_height = hagl < low_height_off
        else:
            state.low_height = hagl < low_height_on
    else:
        state.low_height = False
    effective = base + state.extra + (low_height_add if state.low_height else 0.0)
    return effective, closing, status, state
