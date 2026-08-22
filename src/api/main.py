"""FastAPI surface over the harness, gate, and audit trail. Thin — every
route just calls into eval/, gate/, audit/, redteam/ the same way the CLI
scripts do. No route has any special-cased path to money; /run still goes
through eval.harness.run_strategy, which still only executes through
gate/executor.py.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes import audit as audit_routes
from api.routes import compare as compare_routes
from api.routes import run as run_routes
from api.routes import runs as runs_routes

app = FastAPI(
    title="Bounded Recovery Engine",
    description=(
        "A payment-recovery agent that proposes; a deterministic policy gate disposes. "
        "See /run, /runs/{run_id}, /audit/{run_id}/{decision_id}, /compare."
    ),
    version="0.1.0",
)

app.include_router(run_routes.router)
app.include_router(runs_routes.router)
app.include_router(audit_routes.router)
app.include_router(compare_routes.router)


@app.get("/")
def root():
    return {
        "name": "Bounded Recovery Engine",
        "endpoints": ["/run", "/runs/{run_id}", "/audit/{run_id}/{decision_id}", "/compare", "/docs"],
    }
