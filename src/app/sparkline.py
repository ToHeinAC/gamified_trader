"""Pure SVG path for the balance sparkline."""

from collections.abc import Sequence


def sparkline_path(
    values: Sequence[float], width: float = 120.0, height: float = 32.0, pad: float = 2.0
) -> str:
    """SVG `d` string of a polyline through `values`, scaled into a `width` x `height` box
    with `pad` margin. Empty for fewer than two values; a flat series is drawn mid-height."""
    n = len(values)
    if n < 2:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo
    inner_w, inner_h = width - 2 * pad, height - 2 * pad
    points: list[str] = []
    for i, v in enumerate(values):
        x = pad + inner_w * i / (n - 1)
        y = height / 2 if span == 0 else pad + inner_h * (1 - (v - lo) / span)
        points.append(f"{x:.1f},{y:.1f}")
    return "M" + " L".join(points)
