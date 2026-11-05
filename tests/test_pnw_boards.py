from applybot.sources.pnw_boards import PNW_BOARDS, boards_for


def test_pnw_boards_added_after_configured_and_deduped():
    out = boards_for("greenhouse", {"companies": ["Stripe", "spacex"]})
    assert out[:2] == ["Stripe", "spacex"]
    assert out.count("spacex") == 1
    assert "smartsheet" in out


def test_pnw_boards_can_be_turned_off():
    assert boards_for("lever", {"companies": ["plaid"], "pnw_boards": False}) == ["plaid"]


def test_every_source_has_boards():
    assert all(PNW_BOARDS[s] for s in ("greenhouse", "lever", "ashby"))
