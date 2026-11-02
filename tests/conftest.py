import os, sys, asyncio, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db, notifier, bus
@pytest.fixture
def c(tmp_path):
    notifier.SENT.clear()
    for q in (bus.auditor, bus.analyst, bus.executor, bus.risk):
        while not q.empty(): q.get_nowait()
    return db.connect(str(tmp_path / "t.db"))
MINT = "F6XkiTNf8irwMRSujYmzQhr3FKi2MK88i1uUdCNPpump"
def coin(c, mint=MINT, name="anakin"):
    c.execute("INSERT OR IGNORE INTO coins(mint,name,symbol,migrated_at) VALUES(?,?,?,?)", (mint, name, name.upper(), db.now()))
