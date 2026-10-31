from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .context import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.context


ContextDep = Annotated[AppContext, Depends(get_context)]
