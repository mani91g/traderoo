import json

import pytest

from scanner import kite


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(kite, "_instruments", lambda exchange="NSE": {"INFY": 0.1, "NIFTYFUT": 0.05})
    monkeypatch.setattr(kite, "last_price", lambda symbol, exchange="NSE": None)
    monkeypatch.setattr(kite, "holding_qty", lambda symbol: 10)


def test_long_ticket_rounds_to_tick_and_buffers_the_stop():
    t = kite.build_ticket("infy", 10, 1424.97, 1650.04, 1500.0, buffer_pct=0.5)
    assert (t["sl_trigger"], t["tgt_trigger"]) == (1425.0, 1650.0)
    assert t["sl_limit"] == 1417.9 and t["tgt_limit"] == 1650.0 and t["side"] == 1


def test_stop_must_be_below_price_for_a_long():
    with pytest.raises(kite.KiteError):
        kite.build_ticket("INFY", 10, 1550.0, 1650.0, 1500.0)


def test_intraday_positions_are_refused():
    with pytest.raises(kite.KiteError):
        kite.build_ticket("INFY", 10, 1400.0, 1650.0, 1500.0, product="MIS")


def test_short_ticket_buys_with_lower_trigger_first(monkeypatch):
    sent = {}
    monkeypatch.setattr(kite, "_request", lambda method, path, data=None, **kw: sent.update(data) or {"trigger_id": 7})
    t = kite.build_ticket("NIFTYFUT", 75, 24066.67, 23866.67, 24000.0, exchange="NFO", product="NRML", side=-1,
                          ltp=23900.0)
    assert kite.place_gtt(t) == 7
    cond, orders = json.loads(sent["condition"]), json.loads(sent["orders"])
    assert cond["trigger_values"] == [23866.65, 24066.65]
    assert [o["transaction_type"] for o in orders] == ["BUY", "BUY"]
    assert orders[0]["price"] == 23866.65 and orders[1]["price"] > 24066.65   # stop leg buffered above its trigger
