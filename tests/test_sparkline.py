from app.sparkline import sparkline_path


def test_fewer_than_two_values_gives_empty_path() -> None:
    assert sparkline_path([]) == ""
    assert sparkline_path([5.0]) == ""


def test_rising_series_runs_bottom_left_to_top_right() -> None:
    path = sparkline_path([0, 5, 10], width=100, height=20, pad=0)
    assert path == "M0.0,20.0 L50.0,10.0 L100.0,0.0"


def test_falling_series_runs_top_left_to_bottom_right() -> None:
    path = sparkline_path([10, 0], width=100, height=20, pad=0)
    assert path == "M0.0,0.0 L100.0,20.0"


def test_flat_series_is_a_centered_horizontal_line() -> None:
    path = sparkline_path([7, 7, 7], width=100, height=20, pad=0)
    assert path == "M0.0,10.0 L50.0,10.0 L100.0,10.0"


def test_padding_keeps_the_stroke_inside_the_box() -> None:
    path = sparkline_path([0, 10], width=100, height=20, pad=2)
    assert path == "M2.0,18.0 L98.0,2.0"
