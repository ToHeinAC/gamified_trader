from app.theme import DARK, LIGHT, page_css, theme_for


def test_theme_tokens_match_prd() -> None:
    assert LIGHT.name == "hell"
    assert LIGHT.background == "#E3EAF4"
    assert LIGHT.surface == "#F4F7FB"
    assert LIGHT.primary == "#5448E0"
    assert LIGHT.accent == "#1FC1F0"
    assert LIGHT.text == "#1B1F4B"
    assert LIGHT.up == "#22B35E"
    assert LIGHT.down == "#E5484D"

    assert DARK.name == "dunkel"
    assert DARK.background == "#0A1628"
    assert DARK.surface == "#12233A"
    assert DARK.primary == "#1E88E5"
    assert DARK.accent == "#1FC1F0"
    assert DARK.text == "#E8EEF6"
    assert DARK.up == "#22B35E"
    assert DARK.down == "#E5484D"


def test_theme_for() -> None:
    assert theme_for(False) is LIGHT
    assert theme_for(True) is DARK


def test_page_css_contains_tokens() -> None:
    css = page_css()
    assert LIGHT.primary in css
    assert DARK.primary in css
    assert "body.body--dark" in css


def test_page_css_styles_tiles_option_cards_and_sparkline() -> None:
    css = page_css()
    for selector in (".gt-tiles", ".gt-tile-value", ".gt-option", ".gt-risk-bar", ".gt-spark-up"):
        assert selector in css


def test_page_css_uses_tabular_numbers_and_respects_reduced_motion() -> None:
    css = page_css()
    assert "tabular-nums" in css
    assert "prefers-reduced-motion" in css


def test_resolution_grid_tracks_can_shrink_so_the_page_does_not_overflow() -> None:
    css = page_css()
    assert "minmax(0, 64fr) minmax(0, 36fr)" in css
    assert ".gt-resolution-grid > * { min-width: 0; }" in css
