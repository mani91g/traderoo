from scanner import picks, signals
from tests.helpers import frames, random_walk


def test_scan_runs_on_synthetic_data():
    p = frames({f"S{i}": random_walk(320, seed=i) for i in range(40)})
    m = signals.compute(p)
    assert len(m) == 40
    for col in ("rs", "up_status", "up_score", "down_status", "mom_up", "up_tf", "suspect"):
        assert col in m.columns
    assert m["rs"].between(1, 99).all()
    m["fo"] = True
    longs, shorts, near = picks.select(m)
    assert len(longs) <= 10 and len(shorts) <= 10


def test_short_history_is_skipped():
    p = frames({"OLD": random_walk(320, 1), "NEW": random_walk(50, 2)})
    assert list(signals.compute(p).index) == ["OLD"]
