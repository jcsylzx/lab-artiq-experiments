"""Launch the integrated GUI with the ARTIQ Python environment.

If pyserial is installed in another Python environment, set
GUI_EXTRA_PYTHONPATH to that site-packages directory before launching. The
paths are appended, so ARTIQ/MSYS packages keep priority.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path


def append_existing(path_text: str) -> None:
    path = Path(path_text)
    if path.exists() and str(path) not in sys.path:
        sys.path.append(str(path))


for item in os.environ.get("GUI_EXTRA_PYTHONPATH", "").split(os.pathsep):
    if item.strip():
        append_existing(item.strip())

appdata = os.environ.get("APPDATA")
if appdata:
    version = f"Python{sys.version_info.major}{sys.version_info.minor}"
    append_existing(str(Path(appdata) / "Python" / version / "site-packages"))

from main_gui import main


if __name__ == "__main__":
    main()
