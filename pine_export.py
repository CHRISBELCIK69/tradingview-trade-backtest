"""
Fills trade_replay.pine with your option trades so it can be pasted into
TradingView's Pine Editor. Pine can't read files or sheets, so the trades
have to be written into the script; re-export after new trades.

    python3 pine_export.py trades.csv                  # every trade
    python3 pine_export.py trades.csv -s AMD           # only AMD
    python3 pine_export.py --url "https://docs.google.com/.../pub?output=csv"
    python3 pine_export.py -                           # paste rows, then Ctrl+D

Input is the eod_trade_logger "Trades" tab layout:
    symbol, contract, opened_at, entry_price, exit_price, quantity,
    pnl_dollars, pnl_pct, duration_sec, open_order_id, close_order_id, status
Comma- or tab-separated (rows copied straight out of Google Sheets paste
as tabs). A header line is optional; without one that column order is
assumed. Header names are matched loosely ("Entry Time", "Qty", ...).

Only the Python standard library is used.
"""

import argparse
import csv
import io
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_replay.pine")
MARKER = "//@@TRADES@@"

SHEET_COLUMNS = [
    "symbol", "contract", "opened_at", "entry_price", "exit_price", "quantity",
    "pnl_dollars", "pnl_pct", "duration_sec", "open_order_id", "close_order_id", "status",
]

COLUMN_ALIASES = {
    "symbol": ["symbol", "option_symbol", "occ_symbol", "occ"],
    "contract": ["contract", "description", "label"],
    "opened_at": ["opened_at", "entry_time", "open_time", "opened", "entry_datetime", "entry_date"],
    "closed_at": ["closed_at", "exit_time", "close_time", "closed", "exit_datetime"],
    "entry_price": ["entry_price", "entry", "open_price", "buy_price"],
    "exit_price": ["exit_price", "exit", "close_price", "sell_price"],
    "quantity": ["quantity", "qty", "contracts", "size"],
    "duration_sec": ["duration_sec", "duration_seconds", "duration"],
}

# Weekly/PM-settled index roots, charted on TradingView under the plain index.
UNDERLYING_ROOT_MAP = {"SPXW": "SPX", "NDXP": "NDX", "RUTW": "RUT", "VIXW": "VIX"}

_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")

_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
]


def _norm_header(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", (name or "").strip().lower())


def parse_occ(symbol: str) -> Optional[dict]:
    """'SPY261016C00665000' -> underlying/expiry/type/strike, or None if it isn't an OCC symbol."""
    m = _OCC_RE.match((symbol or "").strip().upper())
    if not m:
        return None
    root, yy, mm, dd, cp, strike_raw = m.groups()
    return {
        "underlying": UNDERLYING_ROOT_MAP.get(root, root),
        "expiry": f"20{yy}-{mm}-{dd}",
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike_raw) / 1000,
        "label": f"{root} {mm}/{dd}/{yy} ${int(strike_raw) / 1000:g} {'Call' if cp == 'C' else 'Put'}",
    }


def _to_float(value) -> Optional[float]:
    text = str(value or "").strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(text) if text not in ("", "-", "—") else None
    except ValueError:
        return None


def _to_utc(value, tz: ZoneInfo) -> Optional[datetime]:
    """ISO or Sheets-style timestamp; values without an offset are read in `tz`."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        for fmt in _TIME_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def read_rows(text: str) -> list:
    """Rows as dicts; the first line is a header only if it names a symbol column."""
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return []
    records = list(csv.reader(lines, delimiter="\t" if "\t" in lines[0] else ","))
    if any(_norm_header(c) in COLUMN_ALIASES["symbol"] for c in records[0]):
        header, records = records[0], records[1:]
    else:
        header = SHEET_COLUMNS
    return [{_norm_header(h): (rec[i].strip() if i < len(rec) else "") for i, h in enumerate(header)} for rec in records]


def parse_trades(rows: list, tz_name: str = "UTC") -> tuple:
    """(trades, errors); a row that can't be backtested is reported, not silently dropped."""
    tz = ZoneInfo(tz_name)
    trades, errors = [], []
    for n, row in enumerate(rows, start=1):
        field = {
            key: next((row[a] for a in aliases if str(row.get(a) or "").strip()), None)
            for key, aliases in COLUMN_ALIASES.items()
        }
        occ = parse_occ(field["symbol"])
        opened = _to_utc(field["opened_at"], tz)
        entry = _to_float(field["entry_price"])
        problems = []
        if occ is None:
            problems.append(f"symbol {field['symbol']!r} isn't an OCC option symbol")
        if opened is None:
            problems.append("missing/unreadable entry time")
        if not entry:
            problems.append("missing entry price")
        if problems:
            errors.append(f"Row {n}: " + "; ".join(problems))
            continue
        closed = _to_utc(field["closed_at"], tz)
        duration = _to_float(field["duration_sec"])
        if closed is None and duration is not None:
            closed = opened + timedelta(seconds=duration)
        trades.append({
            "underlying": occ["underlying"],
            "contract": field["contract"] or occ["label"],
            "option_type": occ["option_type"],
            "strike": occ["strike"],
            "expiry": occ["expiry"],
            "opened_at": opened,
            "closed_at": closed,
            "entry_price": entry,
            "exit_price": _to_float(field["exit_price"]),
            "quantity": _to_float(field["quantity"]) or 1.0,
        })
    return trades, errors


def _ts_utc(dt: datetime) -> str:
    return f'timestamp("UTC", {dt.year}, {dt.month}, {dt.day}, {dt.hour}, {dt.minute}, {dt.second})'


def trade_line(t: dict) -> str:
    y, m, d = (int(x) for x in t["expiry"].split("-"))
    has_exit = t["closed_at"] is not None and t["exit_price"] is not None
    contract = t["contract"].replace("\n", " ")
    return (
        f'    addTrade("{t["underlying"]}", {_ts_utc(t["opened_at"])}, '
        f'{_ts_utc(t["closed_at"]) if has_exit else "na"}, {float(t["entry_price"])!r}, '
        f'{repr(float(t["exit_price"])) if has_exit else "na"}, {"true" if t["option_type"] == "call" else "false"}, '
        f'{float(t["strike"])!r}, timestamp("America/New_York", {y}, {m}, {d}, 16, 0), {float(t["quantity"])!r})'
        f"  // {contract}"
    )


def build_pine(trades: list, symbol: str = "") -> str:
    """The script with `trades` (optionally one underlying) filled in, oldest first as the script expects."""
    if symbol:
        trades = [t for t in trades if t["underlying"].upper() == symbol.upper()]
    if not trades:
        raise ValueError(f"no trades{f' for {symbol.upper()}' if symbol else ''} to export")
    trades = sorted(trades, key=lambda t: t["opened_at"])
    with open(TEMPLATE) as f:
        template = f.read()
    return template.replace(MARKER, "\n".join(trade_line(t) for t in trades))


def _read_source(args) -> str:
    if args.url:
        with urllib.request.urlopen(args.url, timeout=20) as resp:
            text = resp.read().decode("utf-8-sig")
        if "<html" in text[:500].lower():
            sys.exit("That link returned a web page, not CSV: in Sheets use File > Share > Publish to web > (the tab) > CSV")
        return text
    if args.source == "-":
        if sys.stdin.isatty():
            print("Paste trade rows, then press Ctrl+D:", file=sys.stderr)
        return sys.stdin.read()
    if args.source:
        with open(args.source, newline="", encoding="utf-8-sig") as f:
            return f.read()
    sys.exit("Give a CSV file, '-' to paste rows, or --url with a published sheet link (see --help)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write your option trades into the TradingView backtest script.")
    parser.add_argument("source", nargs="?", help="CSV/TSV file of trades, or '-' to paste rows on stdin")
    parser.add_argument("--url", help="a Google Sheet tab published to the web as CSV")
    parser.add_argument("-s", "--symbol", default="", help="only this underlying (AMD, SPY, SPX, ...)")
    parser.add_argument("-o", "--out", default="", help="output file (default trade_replay_<symbol|all>.pine)")
    parser.add_argument("--tz", default="UTC", help="timezone of timestamps without an offset (default UTC, what eod_trade_logger writes)")
    args = parser.parse_args()

    trades, errors = parse_trades(read_rows(_read_source(args)), args.tz)
    for err in errors:
        print(f"skip  {err}", file=sys.stderr)
    try:
        script = build_pine(trades, args.symbol)
    except ValueError as exc:
        sys.exit(str(exc))
    out = args.out or f"trade_replay_{args.symbol.lower() or 'all'}.pine"
    with open(out, "w") as f:
        f.write(script)
    count = script.count('\n    addTrade("')
    print(f"wrote {out} with {count} trade(s): open it, copy everything, paste into TradingView's Pine Editor")


if __name__ == "__main__":
    main()
