"""Design tokens and CSS for the light/dark theme."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    surface: str
    primary: str
    accent: str
    text: str
    up: str
    down: str
    grid: str
    muted: str


LIGHT = Theme(
    "hell",
    "#E3EAF4",
    "#F4F7FB",
    "#5448E0",
    "#1FC1F0",
    "#1B1F4B",
    "#22B35E",
    "#E5484D",
    "#D3DCE8",
    "#8A93B2",
)
DARK = Theme(
    "dunkel",
    "#0A1628",
    "#12233A",
    "#1E88E5",
    "#1FC1F0",
    "#E8EEF6",
    "#22B35E",
    "#E5484D",
    "#1E3350",
    "#7F8FA6",
)


def theme_for(is_dark: bool) -> Theme:
    return DARK if is_dark else LIGHT


def _tokens_css() -> str:
    return f"""
:root {{
    --gt-bg: {LIGHT.background};
    --gt-surface: {LIGHT.surface};
    --gt-text: {LIGHT.text};
    --q-primary: {LIGHT.primary};
    --q-accent: {LIGHT.accent};
    --gt-up: {LIGHT.up};
    --gt-border: {LIGHT.grid};
    --gt-muted: color-mix(in srgb, {LIGHT.text} 66%, {LIGHT.surface});
    --gt-up-text: #14804A;
    --gt-down-text: #C62F34;
}}
body.body--dark {{
    --gt-bg: {DARK.background};
    --gt-surface: {DARK.surface};
    --gt-text: {DARK.text};
    --q-primary: {DARK.primary};
    --q-accent: {DARK.accent};
    --gt-up: {DARK.up};
    --gt-border: {DARK.grid};
    --gt-muted: color-mix(in srgb, {DARK.text} 66%, {DARK.surface});
    --gt-up-text: {DARK.up};
    --gt-down-text: #F2777B;
}}
"""


def _base_css() -> str:
    return """
body {
    background: var(--gt-bg);
    color: var(--gt-text);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
}
.gt-card {
    background: var(--gt-surface);
    border: 1px solid var(--gt-border);
    border-radius: 16px;
    padding: 16px;
    box-shadow: 0 1px 2px rgba(27, 31, 75, .06), 0 4px 12px rgba(27, 31, 75, .05);
}
body.body--dark .gt-card {
    box-shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 4px 12px rgba(0, 0, 0, .25);
}
.gt-header {
    background: var(--gt-surface) !important;
    color: var(--gt-text) !important;
}
.gt-selected {
    border-color: var(--gt-up);
    box-shadow: 0 0 0 3px rgba(34, 179, 94, .25);
}
"""


def _badge_css() -> str:
    return f"""
.gt-badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: 999px;
    padding: 8px 18px;
    font-weight: 700;
    animation: gt-pop .4s ease-out;
}}
.gt-badge-optimal {{
    background: rgba(34, 179, 94, .18);
    color: {LIGHT.up};
    animation: gt-pop .4s ease-out, gt-glow 1.6s ease-in-out 0.4s 2;
}}
.gt-badge-gut {{
    background: rgba(31, 193, 240, .18);
    color: {LIGHT.accent};
}}
.gt-badge-neutral {{
    background: rgba(138, 147, 178, .18);
    color: {LIGHT.muted};
}}
.gt-badge-schlecht {{
    background: rgba(229, 72, 77, .18);
    color: {LIGHT.down};
}}
.gt-pop-in {{
    animation: gt-pop .35s ease-out;
}}
@keyframes gt-pop {{
    from {{ transform: scale(.85); opacity: 0; }}
    to {{ transform: scale(1); opacity: 1; }}
}}
@keyframes gt-glow {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(34, 179, 94, 0); }}
    50% {{ box-shadow: 0 0 0 8px rgba(34, 179, 94, .18); }}
}}
"""


def _resolution_grid_css() -> str:
    return """
.gt-resolution-grid {
    display: grid;
    width: 100%;
    gap: 16px;
    grid-template-columns: 1fr;
    grid-template-areas: "tiles" "stats" "next" "chart" "result";
}
.gt-resolution-grid > * { min-width: 0; }
.gt-area-result .q-table__container { width: 100%; max-width: 100%; }
.gt-area-result .q-table th, .gt-area-result .q-table td { padding: 2px 4px; font-size: .8rem; }
.gt-area-tiles { grid-area: tiles; }
.gt-area-chart { grid-area: chart; }
.gt-area-result { grid-area: result; }
.gt-area-next {
    grid-area: next; display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.gt-area-stats { grid-area: stats; }
@media (min-width: 1024px) {
    .gt-resolution-grid {
        column-gap: 24px;
        grid-template-columns: minmax(0, 60fr) minmax(0, 40fr);
        row-gap: 8px;
        grid-template-rows: auto auto auto minmax(0, 1fr);
        grid-template-areas: "chart tiles" "chart stats" "chart next" "chart result";
    }
}
"""


def _components_css() -> str:
    return """
.q-btn { text-transform: none !important; letter-spacing: 0 !important; }
.gt-header { border-bottom: 1px solid var(--gt-border); gap: 8px; padding: 8px 16px; }
.gt-header a { color: inherit; text-decoration: none; padding: 6px 12px; border-radius: 999px; }
.gt-header a:hover { background: var(--gt-bg); }
.gt-brand { font-weight: 700; letter-spacing: -.01em; margin-right: 8px; }
.gt-tiles {
    display: grid; gap: 8px; width: 100%;
    grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr);
}
.gt-tile {
    background: var(--gt-surface); border: 1px solid var(--gt-border); border-radius: 12px;
    padding: 6px 12px; display: flex; flex-wrap: wrap; align-items: center; column-gap: 8px;
}
.gt-tile-head {
    display: flex; flex-basis: 100%; align-items: center; gap: 6px; color: var(--gt-muted);
}
.gt-tile-label {
    font-size: .75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.gt-tile-value {
    font-size: clamp(1rem, 4.6vw, 1.15rem); font-weight: 700; white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.gt-spark { flex: 1 1 32px; min-width: 32px; height: 20px; }
.gt-spark-up { color: var(--gt-up); }
.gt-spark-down { color: var(--gt-down-text); }
@media (prefers-reduced-motion: reduce) {
    .gt-option, .gt-badge, .gt-pop-in { animation: none !important; transition: none !important; }
}
"""


def _option_css() -> str:
    """Compact option panels of the decision view and their shared text styles."""
    return """
.gt-option {
    padding: 6px 10px; gap: 4px; border-radius: 12px;
    transition: box-shadow .15s ease, border-color .15s ease;
}
.gt-option-head { display: flex; flex-wrap: wrap; align-items: center; column-gap: 8px; }
.gt-option-money {
    margin-left: auto; display: flex; gap: 4px; font-weight: 600; white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.gt-pick { align-self: center; min-height: 24px !important; padding: 0 6px !important; }
.gt-wait-row .gt-pick { margin-left: auto; }
.gt-wait-row { display: grid; gap: 8px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.gt-caption { font-size: .8rem; color: var(--gt-muted); }
.gt-option:hover { border-color: var(--q-primary); }
.gt-card-title { font-size: 1rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.gt-card-sub, .gt-card-note { font-size: .8rem; color: var(--gt-muted); }
.gt-risk-bar {
    display: flex; gap: 2px; width: 100%; height: 6px; border-radius: 999px; overflow: hidden;
}
.gt-risk-loss { flex: 1; background: var(--gt-down-text); }
.gt-risk-gain { flex: 2; background: var(--gt-up); }
.gt-up { color: var(--gt-up-text); }
.gt-down { color: var(--gt-down-text); }
.gt-details { width: 100%; }
.gt-details .q-item { padding: 0 4px; min-height: 24px; font-size: .8rem; }
.gt-ml { padding: 4px 8px; }
.gt-confirm { width: 100%; min-height: 40px; border-radius: 12px; font-weight: 700; }
"""


def _fit_css() -> str:
    """Desktop: the Spielen views fill exactly one viewport; the chart takes the leftover height.
    `--gt-chrome` is the header plus the page padding around `.gt-fit`."""
    return """
:root { --gt-chrome: 88px; }
.gt-plot { height: 420px; }
@media (min-width: 1024px) {
    .gt-fit { height: calc(100dvh - var(--gt-chrome)); overflow: hidden; }
    .gt-fit > * { min-height: 0; }
    .gt-fit .gt-side, .gt-fit .gt-area-result { overflow-y: auto; padding: 4px; }
    .gt-fit .gt-side > *, .gt-fit .gt-area-result > * { flex-shrink: 0; }
    .gt-plot { height: 720px; }
    .gt-fit .gt-chart-card { flex: 1 1 0; min-height: 0; }
    .gt-fit .gt-plot { flex: 1 1 0; min-height: 0; height: auto; }
}
"""


def page_css() -> str:
    return (
        _tokens_css()
        + _base_css()
        + _badge_css()
        + _resolution_grid_css()
        + _components_css()
        + _option_css()
        + _fit_css()
    )
