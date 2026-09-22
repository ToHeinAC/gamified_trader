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
