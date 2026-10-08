# Insider Tracker

Auto-mirror SEC Form 4 insider open-market purchases into an Alpaca paper (or live) account.

When a CEO, CFO, C-suite officer, or Director buys their own company's stock on the open market with their own money — not a pre-scheduled 10b5-1 plan — this tool sees the filing, sizes a position proportional to their conviction, and submits a notional market buy to Alpaca. Everything is audited in SQLite so you can see what was traded, what was skipped, and why.

---

## What the script actually does

Every time you run `uv run insider-tracker run`, it executes this cycle:

1. **Pulls the SEC Form 4 feed** — the realtime list of insider transactions (CEOs, CFOs, directors, 10% owners buying or selling stock in their own company). Form 4s must be filed within 2 business days of the trade, so this is near-live data.
2. **Parses each filing** — extracts ticker, who traded, their role, transaction code (buy/sell/grant/etc.), shares, price, and whether it was part of a pre-scheduled 10b5-1 plan.
3. **Filters down to high-conviction signals** — only keeps filings where:
   - An insider **bought on the open market** with their own money (transaction code `P`) — the strongest historical predictor of future stock gains.
   - The insider is a **Director, CEO, CFO, President, or other Chief officer** — not lower-level employees.
   - The trade was **not pre-scheduled** via a 10b5-1 plan (those were planned months ago and carry no signal).
4. **Sizes the trade** based on how much the insider spent — bigger conviction from them = bigger position from you. Tiered $100 / $300 / $800 / $1,500 / $3,000, hard-capped at 5% of your account equity.
5. **Submits a market buy** to Alpaca as a notional (fractional-dollar) order. If the market is closed, Alpaca queues it for the next open.
6. **Logs everything to SQLite** (`data/state.db`) so the next run skips filings it already processed and you have an audit trail via `uv run insider-tracker status`.

---

## Requirements

- **Python 3.11+**
- [**uv**](https://github.com/astral-sh/uv) package manager
- **Alpaca paper account** — free, sign up at https://app.alpaca.markets
- **SEC User-Agent** — the SEC requires your name + email in EDGAR requests

---

## Install

From the project root (`C:\Users\username\trading`):

```powershell
uv sync
```

That's it — `uv` reads `pyproject.toml`, creates `.venv`, and installs the `insider-tracker` CLI as an entry point.

### Configure credentials

1. Copy the example env file:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Edit `C:\Users\username\trading\.env` and fill in:
   ```
   SEC_USER_AGENT="Your Name your-email@example.com"
   ALPACA_API_KEY=""
   ALPACA_API_SECRET=""
   ALPACA_PAPER=true
   ```
   Paper keys come from https://app.alpaca.markets/paper/dashboard/overview.

---

## Usage

All commands run from the project root.

### Dry run — safe, touches nothing

```powershell
uv run insider-tracker run --dry-run
```

Logs exactly what it *would* trade. Does **not** submit orders, does **not** write to state. Use this first to sanity-check filters and sizing.

> In dry-run mode, account equity defaults to `$100,000` for sizing-cap calculations. Override with `DRY_RUN_EQUITY=50000` in the environment if you want the cap to reflect a specific equity value.

### Go live (paper account)

```powershell
uv run insider-tracker run
```

Submits real paper orders via Alpaca and persists every decision to `data/state.db`. Re-running within the same cycle is safe — already-processed filings are skipped.

### Audit — recent decisions and trades

```powershell
uv run insider-tracker status
```

Prints the last 25 filings processed (traded / skipped / errored with reason) and the last 25 trades submitted.

---

## Command reference

```
insider-tracker [--config PATH] [--db PATH] [--verbose] <command>
```

### Global flags

| Flag | Default | Description |
| --- | --- | --- |
| `--config PATH` | `./config.yaml` | Path to YAML config file (filters, sizing tiers, polling). |
| `--db PATH` | `./data/state.db` | Path to SQLite state file. |
| `-v`, `--verbose` | off | DEBUG-level logging. |

### Subcommands

| Command | Description |
| --- | --- |
| `run` | Poll EDGAR once, filter, submit orders, persist state. Intended for cron / Task Scheduler. |
| `run --dry-run` | Evaluate filings and log decisions only — no orders, no state writes. |
| `run --live` | Trade real money. Also needs `ALPACA_PAPER=false`. Without both, orders go to paper. |
| `status` | Print recent processed filings and recent trades from the state DB. |

---

## One-click status check (Windows)

A script under `scripts/` creates a taskbar-pinnable shortcut so you can see the last 25 filings + trades without touching a terminal.

### Files

| Path | What it is |
| --- | --- |
| `scripts/create-status-shortcut.ps1` | PowerShell script that creates an `Insider Tracker Status` shortcut on your Desktop, with paths resolved for the current user and clone location. The shortcut runs `cmd.exe /k uv run insider-tracker status` in the project root: a CMD window opens, prints the last run's audit, and stays open until you close it. |

### Setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create-status-shortcut.ps1
```

This writes a fresh shortcut to your Desktop with the correct `WorkingDirectory` for wherever the repo is cloned.

### Pin it

1. Right-click the Desktop shortcut
2. **Show more options** (Windows 11 — skip on Windows 10)
3. **Pin to taskbar**

One click from then on → CMD window with the latest audit.

---

## Configuration (`config.yaml`)

Tunable without touching code.

### Filters

```yaml
filters:
  open_market_only: true      # only transaction code 'P' (open-market purchase)
  exclude_10b5_1: true        # drop pre-scheduled 10b5-1 plan trades
  roles_allowed:              # insider must match at least one of these
    - director
    - ceo
    - cfo
    - chief                   # matches any Chief * Officer (COO, CTO, etc.)
    - president
  min_insider_dollars: 0      # floor on reported insider purchase $
```

### Sizing — tiered by insider purchase size

First matching row wins. Final order is capped at `max_pct_of_equity * account_equity`.

```yaml
sizing:
  tiers:
    - { min: 0,        max: 50000,     notional: 100 }
    - { min: 50000,    max: 250000,    notional: 300 }
    - { min: 250000,   max: 1000000,   notional: 800 }
    - { min: 1000000,  max: 5000000,   notional: 1500 }
    - { min: 5000000,  max: 999999999, notional: 3000 }
  max_pct_of_equity: 0.05     # never exceed 5% of account equity on a single order
```

### Execution

```yaml
execution:
  order_type: market          # Alpaca market order
  time_in_force: day          # queued to next open if market closed
  skip_non_fractionable: false
```

### Polling

```yaml
polling:
  feed_count: 100             # entries to pull from EDGAR feed per run
  max_age_hours: 48           # skip anything older (avoids backfill on first run)
```

---

## Scheduling on Windows

Form 4s can land any time on a business day but cluster around **4–6 PM ET** (after close). Running every 15 minutes during market hours is plenty.

### Quick setup

| Field | Value |
| --- | --- |
| **Program** | `C:\Users\username\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe` |
| **Arguments** | `run insider-tracker run` |
| **Start in** | `C:\Users\username\trading` |

### Full walkthrough (Task Scheduler)

1. Open **Task Scheduler** (`Win+R` → `taskschd.msc`).
2. Click **Create Task** (*not* "Create Basic Task" — you need the full dialog).
3. **General** tab:
   - Name: `Insider Tracker`
   - ☑ Run whether user is logged on or not
   - ☑ Run with highest privileges *(optional — avoids permission issues)*
4. **Triggers** tab → **New…**:
   - Begin: **On a schedule**, **Daily**, start at **~9:30 AM**
   - ☑ **Repeat task every 15 minutes** for a duration of **8 hours**
   - ☑ Enabled
5. **Actions** tab → **New…**:
   - Action: **Start a program**
   - Program/script: `C:\Users\username\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`
   - Add arguments: `run insider-tracker run`
   - Start in: `C:\Users\username\trading`
6. **Conditions** tab: uncheck **"Start only if on AC power"** if you're on a laptop.
7. **Settings** tab: ☑ **Run task as soon as possible after a scheduled start is missed**.

### Verify it's working

After the first scheduled run:

```powershell
cd C:\Users\username\trading
uv run insider-tracker status
```

### Capturing logs

Task Scheduler does **not** capture stdout by default. To write logs to a file, change the Action to:

| Field | Value |
| --- | --- |
| **Program** | `C:\Windows\System32\cmd.exe` |
| **Arguments** | `/c "uv run insider-tracker run >> C:\Users\username\trading\data\tracker.log 2>&1"` |
| **Start in** | `C:\Users\username\trading` |

---

## Project layout

```
trading/
├── config.yaml              # tunable filters, sizing tiers, polling
├── pyproject.toml           # uv / pip project definition
├── .env                     # SEC user-agent + Alpaca keys (gitignored)
├── .env.example             # template
├── data/
│   └── state.db             # SQLite audit + dedupe store (gitignored)
├── scripts/
│   └── create-status-shortcut.ps1      # creates the Desktop/taskbar shortcut for `status`
└── insider_tracker/
    ├── cli.py               # argparse entry point: run / status
    ├── edgar.py             # SEC EDGAR Form 4 feed + XML parsing
    ├── filters.py           # role / tx-code / 10b5-1 gate
    ├── sizer.py             # tiered notional sizing + equity cap
    ├── alpaca_client.py     # Alpaca account + submit_notional_buy
    └── state.py             # SQLite processed-filings + trades log
```

---

## How sizing works in practice

> An insider CEO buys $420,000 of their company on the open market, code `P`, not 10b5-1. Tier row 2 (`50k ≤ $ < 250k`)… wait, $420k falls in row 3 (`250k ≤ $ < 1M`) → **$800 notional**. If your paper equity is $10,000, the 5% cap kicks in and reduces the order to **$500**. The order is submitted as a fractional-dollar notional market buy to Alpaca.

---

## Notes & caveats

- **Paper unless you ask twice.** Orders go to the paper endpoint unless `ALPACA_PAPER=false` is set *and* you pass `run --live`. A typo or a blank value stays on paper.
- **Idempotent by accession.** Every Form 4 has a unique `accession` number. The state DB records every one it sees, so re-runs are safe and cheap.
- **Buys only.** There is no sell-side logic — this mirrors insider **conviction**, not exits. Close positions manually in Alpaca.
- **Not financial advice.** You are running an automated strategy. Understand it, dry-run it, watch it for a while on paper before considering anything else.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ALPACA_API_KEY missing` | `.env` not present or keys blank — copy from `.env.example` and fill in. |
| SEC requests returning 403 | `SEC_USER_AGENT` must include a real name + email — SEC enforces this. |
| Task runs but nothing trades | Normal — most filings are rejected by the filters. Run `status` to see reasons. |
| "not tradable on Alpaca" | Symbol isn't in Alpaca's universe (OTC, foreign, halted). Logged and skipped. |
| Want to re-process everything | Stop tasks, delete `data/state.db`, run again. First run will skip items older than `max_age_hours`. |
