"""`python -m diting` entry point.

Delegates to the same `cli.main()` the `diting` console script uses, so a
detached capture session can spawn `python -m diting stream …` with the
running interpreter / venv without depending on `diting` being on PATH.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    main()
