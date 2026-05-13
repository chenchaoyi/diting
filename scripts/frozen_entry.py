"""PyInstaller entry-point stub.

PyInstaller compiles the script you point it at AS a top-level
module, which breaks ``from .x import y`` style relative imports
inside the diting package. A stub that imports ``diting.cli.main``
preserves the package context — the same way pyproject.toml's
``[project.scripts]`` entry calls into ``main`` via ``diting.cli:main``.

Only used by ``scripts/build_frozen.py``. Never invoked directly.
"""
from __future__ import annotations

from diting.cli import main


if __name__ == "__main__":
    main()
