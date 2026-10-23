import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pine_export as pe  # noqa: E402

ROW = "AMD260722C00547500\tAMD 07/22/26 $547.50 Call\t2026-07-21 13:36:30\t5.55\t4.5\t1\t-105\t-18.92\t1117\t137715291\t137725502\tfilled"


def calls(script):
    return [ln for ln in script.splitlines() if ln.startswith('    addTrade("')]


def test_pasted_sheet_row_without_header():
    trades, errors = pe.parse_trades(pe.read_rows(ROW))
    assert errors == []
    t = trades[0]
    assert t["underlying"] == "AMD" and t["strike"] == 547.5 and t["option_type"] == "call"
    assert t["opened_at"] == datetime(2026, 7, 21, 13, 36, 30, tzinfo=timezone.utc)
    assert t["closed_at"] == datetime(2026, 7, 21, 13, 55, 7, tzinfo=timezone.utc)  # opened + duration_sec


def test_csv_with_loose_headers_and_local_timezone():
    text = "Symbol,Entry Time,Exit Time,Entry,Exit,Qty\nQQQ261020P00590000,10/19/2026 9:41:40,10/19/2026 10:54:40,$2.10,$2.65,2"
    trades, errors = pe.parse_trades(pe.read_rows(text), "America/New_York")
    assert errors == []
    t = trades[0]
    assert t["opened_at"] == datetime(2026, 10, 19, 13, 41, 40, tzinfo=timezone.utc)
    assert t["option_type"] == "put" and t["quantity"] == 2.0 and t["exit_price"] == 2.65


def test_bad_rows_are_reported():
    trades, errors = pe.parse_trades(pe.read_rows(ROW + "\nnot a trade\tx"))
    assert len(trades) == 1 and len(errors) == 1 and errors[0].startswith("Row 2")


def test_build_pine_fills_trades_oldest_first_and_maps_spxw():
    with open(os.path.join(os.path.dirname(pe.TEMPLATE), "example_trades.csv")) as f:
        trades, errors = pe.parse_trades(pe.read_rows(f.read()))
    assert errors == []
    script = pe.build_pine(trades)
    assert pe.MARKER not in script
    lines = calls(script)
    assert len(lines) == 4
    assert lines[0].startswith('    addTrade("SPY", timestamp("UTC", 2026, 10, 16, 14, 2, 11), timestamp("UTC", 2026, 10, 16, 14, 47, 21), 1.42, 1.88, true, 665.0')
    assert lines[-1].startswith('    addTrade("SPX"')  # SPXW is charted as SPX
    assert len(calls(pe.build_pine(trades, "spy"))) == 2


def test_trade_without_exit_exports_na():
    trades, _ = pe.parse_trades(pe.read_rows("symbol,opened_at,entry_price\nSPY261016C00665000,2026-10-16 14:02:11,1.42"))
    line = calls(pe.build_pine(trades))[0]
    assert 'timestamp("UTC", 2026, 10, 16, 14, 2, 11), na, 1.42, na, true' in line


def test_no_matching_trades_is_an_error():
    trades, _ = pe.parse_trades(pe.read_rows(ROW))
    try:
        pe.build_pine(trades, "TSLA")
    except ValueError as exc:
        assert "TSLA" in str(exc)
    else:
        raise AssertionError("expected ValueError")
