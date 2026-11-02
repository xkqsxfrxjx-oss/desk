"""SQLite (WAL) data model, STEP 4. Times are ISO-8601 UTC strings.
Extra columns beyond the brief: positions.stop_pct + status (per-position stop, LIVE 'exiting'),
signals.reason. Constraints: FKs to coins, enums, one non-closed position per mint, one signal per mint."""
import os, sqlite3
from datetime import datetime, timezone
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "desk.db")
MODE = "CHECK(mode IN('PAPER','LIVE'))"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS coins (mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, pool TEXT, migrated_at TEXT NOT NULL,
  creator TEXT, creator_balance_at_migration TEXT, holders INTEGER);
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), ts TEXT NOT NULL,
  liquidity_usd REAL, top10_pct REAL, h1_change_pct REAL, age_min INTEGER,
  verdict TEXT NOT NULL CHECK(verdict IN('pass','kill')), reason TEXT);
CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), ts TEXT NOT NULL,
  layer INTEGER NOT NULL CHECK(layer BETWEEN 1 AND 8), name TEXT NOT NULL, value_text TEXT,
  pass INTEGER CHECK(pass IN(0,1)), source TEXT CHECK(source IN('rpc','rugcheck')), UNIQUE(mint,layer));
CREATE TABLE IF NOT EXISTS verdicts (id INTEGER PRIMARY KEY, mint TEXT NOT NULL UNIQUE REFERENCES coins(mint), ts TEXT NOT NULL,
  alive_6h REAL CHECK(alive_6h BETWEEN 0 AND 1), organic REAL CHECK(organic BETWEEN 0 AND 1),
  flush REAL CHECK(flush BETWEEN 0 AND 1), chase REAL CHECK(chase BETWEEN 0 AND 1),
  score INTEGER CHECK(score BETWEEN 0 AND 100), pass INTEGER NOT NULL CHECK(pass IN(0,1)), reason TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, mint TEXT NOT NULL UNIQUE REFERENCES coins(mint), ts TEXT NOT NULL,
  price REAL, size_usd REAL, stack_pct REAL, link TEXT NOT NULL CHECK(link LIKE '%r=savipww%'), mode TEXT NOT NULL {MODE},
  status TEXT NOT NULL CHECK(status IN('sent','bought','skipped','missed')), reason TEXT);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, mint TEXT NOT NULL REFERENCES coins(mint), opened_at TEXT NOT NULL,
  entry_price REAL NOT NULL CHECK(entry_price>0), size_usd REAL NOT NULL CHECK(size_usd>0), peak_price REAL NOT NULL,
  stop_price REAL NOT NULL, stop_pct REAL NOT NULL, trail_active INTEGER NOT NULL DEFAULT 0 CHECK(trail_active IN(0,1)),
  closed_at TEXT, exit_price REAL, exit_reason TEXT CHECK(exit_reason IN('stop','trail','timeout','pulled')),
  pnl_usd REAL, fees_usd REAL, mode TEXT NOT NULL {MODE},
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN('open','exiting','closed')));
CREATE UNIQUE INDEX IF NOT EXISTS one_open_per_mint ON positions(mint) WHERE status!='closed';
CREATE TRIGGER IF NOT EXISTS stop_never_down BEFORE UPDATE OF stop_price ON positions
  WHEN NEW.stop_price < OLD.stop_price BEGIN SELECT RAISE(ABORT,'stop never moves down'); END;
CREATE TRIGGER IF NOT EXISTS trail_never_off BEFORE UPDATE OF trail_active ON positions
  WHEN OLD.trail_active=1 AND NEW.trail_active=0 BEGIN SELECT RAISE(ABORT,'trail never turns off'); END;
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, ts TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN('bought','sold','stopped','rejected')), mint TEXT REFERENCES coins(mint),
  agent TEXT NOT NULL CHECK(agent IN('scanner','auditor','analyst','executor','risk')), title TEXT NOT NULL, subtitle TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS prices (mint TEXT NOT NULL, ts TEXT NOT NULL, price REAL, volume_m5 REAL, PRIMARY KEY(mint,ts));
CREATE TABLE IF NOT EXISTS balance (ts TEXT PRIMARY KEY, value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS change_log (ts TEXT NOT NULL, key TEXT NOT NULL, old TEXT, new TEXT, who TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skips (mint TEXT PRIMARY KEY, until TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS heartbeats (agent TEXT PRIMARY KEY, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS scans_mint ON scans(mint);   CREATE INDEX IF NOT EXISTS audits_mint ON audits(mint);
CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts); CREATE INDEX IF NOT EXISTS prices_ts ON prices(ts);
"""
def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
def connect(path=DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    for p in ("journal_mode=WAL", "synchronous=NORMAL", "foreign_keys=ON", "busy_timeout=5000"): c.execute("PRAGMA " + p)
    c.executescript(SCHEMA); return c

# --- price writers: 1 DexScreener batch per writer, each writes its own mints only ---
def write_prices(c, rows, ts=None):
    """rows: iterable of (mint, price, volume_m5). Same ts for the whole batch."""
    ts = ts or now()
    c.executemany("INSERT OR REPLACE INTO prices(mint,ts,price,volume_m5) VALUES(?,?,?,?)", [(m, ts, p, v) for m, p, v in rows])
def scanner_mints(c, waiting):          # Scanner, every 60s: its in-memory waiting room
    return list(waiting)
def risk_mints(c):                      # Risk, every 15s: open/exiting positions
    return [r[0] for r in c.execute("SELECT mint FROM positions WHERE status!='closed'")]
def api_mints(c, since, waiting=()):    # api.py, every 60s: tonight's coins not covered above
    covered = set(waiting) | set(risk_mints(c))
    q = """SELECT mint FROM signals WHERE ts>=:s UNION SELECT mint FROM audits WHERE ts>=:s
           UNION SELECT mint FROM positions WHERE opened_at>=:s"""
    return [r[0] for r in c.execute(q, {"s": since}) if r[0] not in covered]

def heartbeat(c, agent): c.execute("INSERT OR REPLACE INTO heartbeats VALUES(?,?)", (agent, now()))
def set_setting(c, key, value, who):
    old = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    t = now()
    with c:
        c.execute("BEGIN")
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?)", (key, str(value), t))
        c.execute("INSERT INTO change_log VALUES(?,?,?,?,?)", (t, key, old[0] if old else None, str(value), who))
