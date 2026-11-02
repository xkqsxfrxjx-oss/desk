import logging, os
from logging.handlers import TimedRotatingFileHandler
LOGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
def logger(name):
    lg = logging.getLogger("desk." + name)
    if not lg.handlers:
        os.makedirs(LOGDIR, exist_ok=True)
        h = TimedRotatingFileHandler(os.path.join(LOGDIR, f"{name}.log"), when="midnight", backupCount=14, utc=True)
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%dT%H:%M:%SZ"))
        logging.Formatter.converter = __import__("time").gmtime
        lg.addHandler(h); lg.setLevel(logging.INFO); lg.propagate = False
    return lg
