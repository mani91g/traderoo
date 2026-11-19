from scanner import fundamentals as f

GOOD = {"sector": "Industrials", "returnOnEquity": 0.2, "profitMargins": 0.1, "revenueGrowth": 0.15,
        "earningsGrowth": 0.2, "debtToEquity": 40.0, "operatingCashflow": 1e9}


def test_all_checks_pass():
    r = f.score(GOOD)
    assert r["score"] == 100 and r["strong"] and r["counted"] == 6


def test_loss_making_company_is_never_strong():
    r = f.score({**GOOD, "profitMargins": -0.05})
    assert not r["strong"] and r["summary"] == "Not profitable"


def test_debt_to_equity_is_read_as_a_percentage():
    passed = dict((name, ok) for name, ok, _ in f.score({**GOOD, "debtToEquity": 84.0})["checks"])
    failed = dict((name, ok) for name, ok, _ in f.score({**GOOD, "debtToEquity": 120.0})["checks"])
    assert passed["Debt / equity below 1"] is True and failed["Debt / equity below 1"] is False


def test_financial_companies_skip_debt_and_cash_flow():
    r = f.score({**GOOD, "sector": "Financial Services", "operatingCashflow": -1e12, "debtToEquity": 900.0})
    assert r["counted"] == 4 and r["strong"]


def test_too_little_data_is_not_strong():
    r = f.score({"profitMargins": 0.1, "revenueGrowth": 0.1})
    assert r["counted"] == 2 and not r["strong"]


def test_no_data():
    assert f.score(None)["score"] is None
