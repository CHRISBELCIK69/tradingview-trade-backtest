# TradingView Trade Backtest

A TradingView strategy that replays **your own option trades**. It enters at the exact times you really entered, then exits by rules you choose, so you can see whether a stop, a target, a trailing stop or a VWAP exit would have beaten the exits you actually took.

Pine Script can't see option prices, so the option is **modeled** from the stock's chart (details in [How the option price is modeled](#how-the-option-price-is-modeled)).

## What's here

| File | What |
|---|---|
| `trade_replay.pine` | The strategy template. Don't paste this one into TradingView: it has no trades in it yet. |
| `pine_export.py` | Writes your trades into the template and saves a ready-to-paste `.pine` file. Python 3.9+, no packages to install. |
| `example_trades.csv` | Four made-up trades in the expected format, to try it out. |

## 1. Export your trades

Pine can't read files or Google Sheets, so your trades get written into the script itself. Pick whichever way you have your trades:

```bash
# A CSV / TSV file
python3 pine_export.py my_trades.csv

# Your Google Sheet tab, published as CSV (File → Share → Publish to web → the Trades tab → CSV)
python3 pine_export.py --url "https://docs.google.com/spreadsheets/d/e/.../pub?gid=0&single=true&output=csv"

# Rows copied straight out of the sheet: paste them, then press Ctrl+D
python3 pine_export.py -
```

Add `-s AMD` to export only one underlying. This writes `trade_replay_amd.pine`; without `-s` you get `trade_replay_all.pine`. Exporting one symbol at a time keeps the script small, and the script only trades the chart's symbol anyway.

Rows that can't be used are listed as `skip  Row N: ...` and left out.

### Trade format

The column order of the `eod_trade_logger` Trades tab:

```
symbol, contract, opened_at, entry_price, exit_price, quantity, pnl_dollars, pnl_pct, duration_sec, open_order_id, close_order_id, status
```

For example (tab-separated, as it comes out of Google Sheets):

```
AMD260722C00547500	AMD 07/22/26 $547.50 Call	2026-07-21 13:36:30	5.55	4.5	1	-105	-18.92	1117	137715291	137725502	filled
```

- **Required:** an OCC option `symbol`, the entry time and the entry price. The exit price and the exit time (`closed_at`, or `opened_at + duration_sec`) are needed for the comparison with your real exits.
- **Header:** optional. With a header, the names are matched loosely (`Entry Time`, `Exit`, `Qty`, ...) and the columns can be in any order.
- **Times:** read as **UTC** unless they carry an offset, because that's what `eod_trade_logger` writes. If your sheet uses Eastern time, add `--tz America/New_York`.
- **Direction:** every trade is treated as a bought call or put (buy to open, sell to close).

## 2. Load it in TradingView

1. Open a chart of the **underlying stock**, not the option: `AMD`, `SPY`, `QQQ`. For SPXW trades open `SPX` (the exporter already maps SPXW to SPX).
2. Pick an **intraday timeframe**. 1m is the most faithful, and 5m loads more history (see [Limits](#limits)).
3. Open the **Pine Editor** tab at the bottom of the chart.
4. Open your exported `.pine` file in any text editor, select everything, copy it, and paste it over whatever is in the Pine Editor.
5. Click **Save** (give it a name), then **Add to chart**.

> **Keep it private.** The script contains your trades. Saving it in the Pine Editor is private to your account, but don't use **Publish script**: that makes it public.

## 3. Set your exit rules

Click the gear next to *Trade Replay Backtest* on the chart (or double-click its name), then open **Inputs**. Every rule set to 0 or unticked is off. Whichever rule triggers first closes the trade.

| Setting | What it does |
|---|---|
| Stop loss (option %) | Exits when the modeled option falls this far below your entry fill. Default 30. |
| Take profit (option %) | Exits when it rises this far above your entry fill. Default 50. |
| Trailing stop from best (option %) | Once the option is above your entry, exits when it falls this far from its best price. |
| Exit when price crosses back through VWAP | For calls: the stock closes back below VWAP. For puts: back above it. |
| Exit when price crosses back through EMA / EMA length | Same check against an EMA (20 by default). |
| Time stop (bars) | Exits after this many bars in the trade. |
| Flat by time of day / Flat by (ET, HHMM) | Exits at or after this Eastern time, e.g. `1555`. |
| Risk-free rate % | Used by the option model. Barely matters over a few days. |
| Commission per contract, each side | Subtracted from both columns of the results table. |
| Label each exit / Mark my real exits | Chart labels, see below. |

A trade still open at expiry is closed at the expiry bar. If the stop and the target are both touched inside the same bar, the stop counts as hit first, the conservative assumption.

## 4. Read the results

**The table in the top-right corner is the result to read.** It's option P&L, comparing the rules with your real exits over the same trades:

| Row | Meaning |
|---|---|
| Trades | Trades on this symbol that were entered and closed. |
| Win rate / Avg per trade / Total $ | For the rules (modeled option prices) and for your real exits (your real fills), after commission. |
| Still open | A trade that hasn't hit any exit rule yet by the last bar. |
| Skipped (overlap) | Entries that came while another trade was still open. The script holds one trade at a time. |
| Before chart history | Your trades older than the oldest bar loaded on this chart, which can't be tested. |
| off-model fill(s) | Entry fills the model couldn't match, see below. |

On the chart:
- Each **rule exit** gets a green or red label with the rule that fired, its %, and your real % for that trade, e.g. `stop -30%` / `real +12%`.
- Your **real exits** are marked with purple `real exit 1.88` labels.
- The **modeled option price** shows in the Data Window (right sidebar) while a trade is open.

**About the Strategy Tester tab:** a strategy can only trade the chart's symbol, so it buys or shorts the stock, sized at the option's delta × 100 shares per contract. Its trade list is handy for seeing entries and exits, but its P&L only roughly tracks the option. Use the table for option P&L.

## Updating

When you have new trades, re-export, then in the Pine Editor select all, paste the new file over the old script, and click **Save**. The chart updates. To try a different symbol, change the chart's symbol, or export just that symbol.

## How the option price is modeled

- **Pinned to your fill.** On your entry bar, the script solves for the implied volatility that makes the Black-Scholes price equal your real entry fill, using the stock's price at that bar's close and the time left until 16:00 ET on expiry day.
- **Held through the trade.** That IV stays fixed. Each later bar is priced from the stock's high, low and close with less time to expiry, so time decay is included. That matters most on 0–1 DTE trades.
- **Your real exit isn't used to shape the model.** That keeps it from leaking into the rules you're testing.
- **Off-model fills.** A fill that no volatility between 1% and 1000% can produce (for example far below intrinsic value) is still traded at the closest possible IV, and counted under "off-model fill(s)".

What the model can't see: IV changing during the trade (a vol crush after news, or a spike into a selloff), the bid/ask spread, and slippage. Treat the rule results as a close estimate. The real-exit column uses your actual fills, so it's exact.

## Limits

- **History depth.** TradingView only loads a limited number of bars, and the limit depends on your plan and the timeframe. On 1m, older trades fall under "Before chart history". Switch to 5m or 15m to reach further back.
- **Market hours.** The script is built for regular-hours trades. A fill outside the chart's session enters on the next bar.
- **Script size.** All trades are written into the script. If TradingView complains that the script is too large, export one symbol at a time with `-s`.

## Tests

```bash
python3 -m pytest -q
```
