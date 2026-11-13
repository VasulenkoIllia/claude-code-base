---
paths:
  - "**/*.py"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- In a project with `pyproject.toml` (a repo of standalone scripts keeps its style): a public function or method has annotated parameters and return; across a module boundary goes a dataclass, `TypedDict` or pydantic model, not a bare `dict` or `Any`; env is read in one settings object, not `os.environ` across the code. A suppression names its rule and reason, no blanket `# type: ignore` or `# noqa`.
- External input (request, env, file, CLI, API or scraped data): validate once at the boundary, inner code gets the parsed value, not the raw `dict`.
- Errors: no bare `except:`, no `except Exception: pass`, no silent `return None`: catch the specific exception, log, re-raise (a new error with `from`); swallow only deliberately, with a comment. Files, sessions, locks, connections under `with` / `async with`.
- HTTP: httpx, requests and aiohttp don't raise on 4xx/5xx: `raise_for_status()`. Network calls and `subprocess` get an explicit timeout (requests has none by default).
- Async: nothing blocking in `async def` (`requests`, `time.sleep`, a sync DB driver): the async client, `asyncio.sleep`, `asyncio.to_thread`; heavy CPU in a process pool. Await every coroutine; keep the task of `create_task` and handle its error; `gather` over an input-sized list under a semaphore; don't swallow `CancelledError`.
- No mutable default argument (`def f(x=[])`): `None`, create inside. No module-level mutable state shared between requests or tasks. Datetimes timezone-aware; money `Decimal` or integer minor units, never `float`.
- SQL values only as bound parameters, never by string formatting (f-string, `%`, `.format()`).
