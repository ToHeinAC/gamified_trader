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


def page_css() -> str:
    return f"""
:root {{
    --gt-bg: {LIGHT.background};
    --gt-surface: {LIGHT.surface};
    --gt-text: {LIGHT.text};
    --q-primary: {LIGHT.primary};
    --q-accent: {LIGHT.accent};
}}
body.body--dark {{
    --gt-bg: {DARK.background};
    --gt-surface: {DARK.surface};
    --gt-text: {DARK.text};
    --q-primary: {DARK.primary};
    --q-accent: {DARK.accent};
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
"""
