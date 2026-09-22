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
}}
body.body--dark {{
    --gt-bg: {DARK.background};
    --gt-surface: {DARK.surface};
    --gt-text: {DARK.text};
    --q-primary: {DARK.primary};
    --q-accent: {DARK.accent};
    --gt-up: {DARK.up};
}}
body {{
    background: var(--gt-bg);
    color: var(--gt-text);
    font-family: system-ui, sans-serif;
}}
.gt-card {{
    background: var(--gt-surface);
    border-radius: 22px;
    padding: 20px;
    box-shadow: 0 8px 24px rgba(27, 31, 75, .08);
}}
body.body--dark .gt-card {{
    box-shadow: 0 8px 24px rgba(0, 0, 0, .35);
}}
.gt-header {{
    background: var(--gt-surface) !important;
    color: var(--gt-text) !important;
}}
.gt-selected {{
    border: 2px solid var(--gt-up);
    box-shadow: 0 0 0 3px rgba(34, 179, 94, .25);
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
.gt-area-tiles { grid-area: tiles; }
.gt-area-chart { grid-area: chart; }
.gt-area-result { grid-area: result; }
.gt-area-next { grid-area: next; }
.gt-area-stats { grid-area: stats; }
@media (min-width: 1024px) {
    .gt-resolution-grid {
        column-gap: 24px;
        grid-template-columns: 64% 36%;
        grid-template-areas: "chart tiles" "chart result" "chart next" "chart stats";
    }
}
"""


def page_css() -> str:
    return _tokens_css() + _resolution_grid_css()
