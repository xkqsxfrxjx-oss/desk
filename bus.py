"""Queues between agents: scanner -> auditor -> analyst -> executor -> risk."""
import asyncio
auditor: asyncio.Queue = asyncio.Queue()
analyst: asyncio.Queue = asyncio.Queue()
executor: asyncio.Queue = asyncio.Queue()
risk: asyncio.Queue = asyncio.Queue()
events: asyncio.Queue = asyncio.Queue(maxsize=10000)   # SSE feed for the app (audit_layer etc.)
def emit(kind, data):
    try: events.put_nowait({"kind": kind, **data})
    except asyncio.QueueFull: pass
