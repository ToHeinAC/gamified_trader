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
    grid-template-areas: "tiles" "chart" "result" "next" "stats";
}
.gt-resolution-grid > * { min-width: 0; }
.gt-area-result .q-table__container { width: 100%; max-width: 100%; }
.gt-area-tiles { grid-area: tiles; }
.gt-area-chart { grid-area: chart; }
.gt-area-result { grid-area: result; }
.gt-area-next { grid-area: next; }
.gt-area-stats { grid-area: stats; }
@media (min-width: 1024px) {
    .gt-resolution-grid {
        column-gap: 24px;
        grid-template-columns: minmax(0, 64fr) minmax(0, 36fr);
        grid-template-areas: "chart tiles" "chart result" "chart next" "chart stats";
    }
}
"""


def _components_css() -> str:
    return """
.q-btn { text-transform: none !important; letter-spacing: 0 !important; }
.gt-header { border-bottom: 1px solid var(--gt-border); gap: 8px; }
.gt-header a { color: inherit; text-decoration: none; padding: 6px 12px; border-radius: 999px; }
.gt-header a:hover { background: var(--gt-bg); }
.gt-brand { font-weight: 700; letter-spacing: -.01em; margin-right: 8px; }
.gt-tiles {
    display: grid; gap: 12px; width: 100%;
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
}
.gt-tile {
    background: var(--gt-surface); border: 1px solid var(--gt-border); border-radius: 16px;
    padding: 14px 16px; display: flex; flex-direction: column; gap: 4px;
}
.gt-tile-head { display: flex; align-items: center; gap: 6px; color: var(--gt-muted); }
.gt-tile-label { font-size: .8rem; }
.gt-tile-value {
    font-size: clamp(1.1rem, 4.6vw, 1.5rem); font-weight: 700; white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.gt-spark { width: 100%; height: 32px; margin-top: 4px; }
.gt-spark-up { color: var(--gt-up); }
.gt-spark-down { color: var(--gt-down-text); }
.gt-option { gap: 6px; transition: box-shadow .15s ease, border-color .15s ease; }
.gt-option:hover { border-color: var(--q-primary); }
.gt-card-title { font-size: 1.1rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.gt-card-sub, .gt-card-note { font-size: .8rem; color: var(--gt-muted); }
.gt-risk { display: flex; flex-direction: column; gap: 4px; width: 100%; }
.gt-risk-bar { display: flex; gap: 2px; height: 8px; border-radius: 999px; overflow: hidden; }
.gt-risk-loss { flex: 1; background: var(--gt-down-text); }
.gt-risk-gain { flex: 2; background: var(--gt-up); }
.gt-risk-figure { display: flex; justify-content: space-between; align-items: baseline; }
.gt-risk-value { font-size: .95rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.gt-up { color: var(--gt-up-text); }
.gt-down { color: var(--gt-down-text); }
.gt-details { width: 100%; }
.gt-confirm { width: 100%; min-height: 48px; border-radius: 12px; font-weight: 700; }
@media (prefers-reduced-motion: reduce) {
    .gt-option, .gt-badge, .gt-pop-in { animation: none !important; transition: none !important; }
}
"""


def page_css() -> str:
    return _tokens_css() + _base_css() + _badge_css() + _resolution_grid_css() + _components_css()
