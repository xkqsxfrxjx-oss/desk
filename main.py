"""One asyncio process: 5 agents + plan B JSON writer/publisher + Telegram long polling + heartbeats (PAPER)."""
import asyncio, fcntl, os, sys, time
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "MOVED_TO_VPS")):
    sys.exit("desk moved to VPS (data/MOVED_TO_VPS present) - not starting here")
import config, db, notifier
from agents.scanner import Scanner
from agents.auditor import Auditor
from agents.analyst import Analyst
from agents.executor import Executor, stack
from agents.risk import Risk
from api import Api
from telegram import Telegram
from logs_util import logger
log = logger("main")

async def beat(c, name, task):
    wall, mono = time.time(), time.monotonic()
    while True:
        w, m = time.time(), time.monotonic()
        gap = (w - wall) - (m - mono)
        if gap > 60: log.info(f"{name}: box was frozen ~{gap:.0f}s (wall clock jumped, process paused)")
        wall, mono = w, m
        if not task.done(): db.heartbeat(c, name)
        else: log.info(f"{name} task ended: {task.exception() if not task.cancelled() else 'cancelled'}")
        await asyncio.sleep(30)

async def balance_writer(c):
    while True:
        c.execute("INSERT OR REPLACE INTO balance VALUES(?,?)", (db.now(), stack(c))); await asyncio.sleep(60)

async def main(only=None):
    c = db.connect()
    if config.get(c, "desk.mode") != "PAPER": sys.exit("this build runs PAPER only")
    tg = Telegram(c)
    if tg.token: notifier.BACKEND = tg
    sc = Scanner(c); au = Auditor(c); tg.auditor = au
    ok, msg = config.ticket_check(c, stack(c))
    log.info(f"start PAPER stack={stack(c)} ticket_check={ok} {msg or ''}")
    if msg: await notifier.push(("PAPER · " + msg) if ok else msg, kind="alert")
    parts = {"scanner": sc, "auditor": au, "analyst": Analyst(c), "executor": Executor(c), "risk": Risk(c),
             "api": Api(c, sc), "telegram": tg}
    tasks = []
    for n, a in parts.items():
        if only and n not in only: continue
        t = asyncio.create_task(a.run(), name=n); tasks += [t, asyncio.create_task(beat(c, n, t))]
    tasks.append(asyncio.create_task(balance_writer(c)))
    await asyncio.gather(*tasks)

def single_instance():
    os.makedirs("data", exist_ok=True)
    f = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "main.lock"), "w")
    try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: sys.exit("main.py already running (data/main.lock held), not starting a second copy")
    f.write(str(os.getpid())); f.flush(); return f

if __name__ == "__main__":
    _lock = single_instance()
    asyncio.run(main(set(sys.argv[1:]) or None))
