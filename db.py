"""SQLite (WAL) data model for the desk. All times ISO-8601 UTC strings."""
import sqlite3, os
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "desk.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings  (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coins     (mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, pool TEXT, signature TEXT,
  creator TEXT, creator_balance_at_migration TEXT, supply TEXT, decimals INTEGER, token_program TEXT,
  migrated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting', holders INTEGER, coin_url TEXT, night_id INTEGER);
CREATE TABLE IF NOT EXISTS scans     (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), ts TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK(verdict IN('pass','kill','drop')), reason TEXT, liquidity_usd REAL, top10_pct REAL,
  h1_change_pct REAL, age_min INTEGER, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audits    (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), ts TEXT NOT NULL,
  passed INTEGER NOT NULL, layers_checked INTEGER NOT NULL, reason TEXT, holders INTEGER, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_layers (audit_id INTEGER NOT NULL REFERENCES audits(id), n INTEGER NOT NULL CHECK(n BETWEEN 1 AND 8),
  name TEXT NOT NULL, pass INTEGER, value TEXT, source TEXT, ms INTEGER, ts TEXT NOT NULL, PRIMARY KEY(audit_id,n));
CREATE TABLE IF NOT EXISTS analyses  (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), ts TEXT NOT NULL,
  alive_6h REAL, organic REAL, flush REAL, chase REAL, score INTEGER, passed INTEGER NOT NULL, failed TEXT,
  model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, state_hash TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals   (id INTEGER PRIMARY KEY, mint TEXT NOT NULL UNIQUE REFERENCES coins(mint), ts TEXT NOT NULL,
  signal_price REAL, size_usd REAL, stack_pct REAL, cap_hit TEXT, link TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN('PAPER','LIVE')),
  status TEXT NOT NULL CHECK(status IN('sent','bought','skipped','missed')), reason TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), name TEXT,
  mode TEXT NOT NULL CHECK(mode IN('PAPER','LIVE')), opened_at TEXT NOT NULL, entry_price REAL NOT NULL, size_usd REAL NOT NULL,
  peak_price REAL NOT NULL, stop_pct REAL NOT NULL, stop_line REAL NOT NULL, trail_active INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN('open','exiting','closed')), exit_reason TEXT CHECK(exit_reason IN('stop','trail','timeout','pulled')),
  exit_price REAL, closed_at TEXT, pnl_usd REAL, pct REAL, fees_usd REAL, no_price_polls INTEGER NOT NULL DEFAULT 0, link TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_per_mint ON positions(mint) WHERE status!='closed';
CREATE TABLE IF NOT EXISTS prices    (mint TEXT NOT NULL, ts TEXT NOT NULL, price_usd REAL, volume_m5 REAL, liquidity_usd REAL, PRIMARY KEY(mint,ts));
CREATE TABLE IF NOT EXISTS activity  (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, agent TEXT NOT NULL, mint TEXT, title TEXT NOT NULL,
  detail TEXT, value TEXT, mode TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skips     (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, mint TEXT NOT NULL, agent TEXT NOT NULL, rule TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS pushes    (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, channel TEXT NOT NULL, kind TEXT NOT NULL, mint TEXT,
  text TEXT NOT NULL, link TEXT, ok INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 1, tg_message_id INTEGER);
CREATE TABLE IF NOT EXISTS heartbeats(agent TEXT PRIMARY KEY, ts TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS ws_events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, event TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS nights    (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, mode TEXT NOT NULL,
  start_stack REAL, end_stack REAL, report_url TEXT, layer8_kills INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS balance   (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, mode TEXT NOT NULL, stack REAL NOT NULL, note TEXT);
CREATE INDEX IF NOT EXISTS scans_mint ON scans(mint); CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
CREATE INDEX IF NOT EXISTS audits_mint ON audits(mint); CREATE INDEX IF NOT EXISTS analyses_mint ON analyses(mint);
"""
def connect(path=DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA busy_timeout=5000")
    c.executescript(SCHEMA); return c
