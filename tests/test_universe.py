from app.universe import MARKETS, load_universe, ticker_names


def test_universe_is_well_formed() -> None:
    entries = load_universe()

    assert len(entries) >= 600

    tickers = [e.ticker for e in entries]
    assert len(tickers) == len(set(tickers)), "duplicate tickers"

    for e in entries:
        assert e.ticker, "empty ticker"
        assert e.name, "empty name"
        assert e.market, "empty market"
        assert e.market in MARKETS
        assert e.ticker == e.ticker.upper()
        assert " " not in e.ticker
        if e.market in ("DAX", "MDAX", "SDAX"):
            # Almost all trade on Xetra (.DE); Airbus (DAX) is Euronext-Paris-primary (AIR.PA).
            assert "." in e.ticker


def test_ticker_names_maps_ticker_to_name() -> None:
    names = ticker_names()
    entries = load_universe()
    assert len(names) == len(entries)
    assert names[entries[0].ticker] == entries[0].name
