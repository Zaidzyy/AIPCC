"""The evaluation results, read-only.

Serves the committed `app/eval/results/latest.json` — the last run of
`python -m app.eval.run`. It does **not** run an evaluation: a live run costs
money and takes half a minute, and an endpoint that could be made to spend an
API budget by being refreshed is not an endpoint, it is a bill. The harness is
a command; this shows what it last said.

Authenticated but not admin-only. "How good is this system's output" is a
question every analyst using it should be able to answer, and the file contains
no user data — a synthetic log, catalogue versions, and rates.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.db import models

router = APIRouter(prefix="/eval", tags=["evaluation"])

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "results" / "latest.json"


@router.get("/latest")
def latest(_: models.Users = Depends(get_current_user)) -> dict:
    """The most recent committed evaluation run.

    404 when there is none, rather than an empty shape that would render as a
    page of zeros — "nobody has evaluated this" and "it scored zero" are the
    pair of states this project never lets look alike.
    """
    if not RESULTS.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no evaluation has been run yet — see backend/EVAL.md",
        )
    try:
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"the evaluation result file is not readable: {exc}",
        ) from exc
