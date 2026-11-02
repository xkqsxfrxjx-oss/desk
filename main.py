"""One asyncio process: agents + heartbeats (PAPER). Telegram/API come later."""
import asyncio, sys
import config, db
from agents.scanner import Scanner
from agents.auditor import Auditor
from agents.analyst import Analyst
from agents.executor import Executor, stack
from agents.risk import Risk
from logs_util import logger
log = logger("main")

async def beat(c, name, task):
    while True:
        if not task.done(): db.heartbeat(c, name)
        await asyncio.sleep(30)

async def balance_writer(c):
    while True:
        c.execute("INSERT OR REPLACE INTO balance VALUES(?,?)", (db.now(), stack(c))); await asyncio.sleep(60)

async def main(only=None):
    c = db.connect()
    if config.get(c, "desk.mode") != "PAPER": sys.exit("STEP 5 runs PAPER only")
    ok, msg = config.ticket_check(c, stack(c))
    log.info(f"start PAPER stack={stack(c)} ticket_check={ok} {msg or ''}"); print("ticket check:", msg or "ok")
    agents = {"scanner": Scanner(c), "auditor": Auditor(c), "analyst": Analyst(c), "executor": Executor(c), "risk": Risk(c)}
    tasks = []
    for n, a in agents.items():
        if only and n not in only: continue
        t = asyncio.create_task(a.run(), name=n); tasks.append(t); tasks.append(asyncio.create_task(beat(c, n, t)))
    tasks.append(asyncio.create_task(balance_writer(c)))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:]) or None))
