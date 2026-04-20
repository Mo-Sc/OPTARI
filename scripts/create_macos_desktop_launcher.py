#!/usr/bin/env python3
"""Create a PATARI launcher on macOS desktop.
Run this script with the same Python environment where PATARI is installed.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("This helper is intended for macOS only.")

    desktop = Path.home() / "Desktop"
    launcher_path = desktop / "PATARI.command"
    python_exe = Path(sys.executable).resolve()

    script = "\n".join(
        [
            "#!/bin/zsh",
            "set -e",
            f'"{python_exe}" -m patari.launcher',
        ]
    )

    launcher_path.write_text(script + "\n", encoding="utf-8")

    current_mode = launcher_path.stat().st_mode
    launcher_path.chmod(
        current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )

    print(f"Created launcher: {launcher_path}")
    print("You can now double-click PATARI.command on your Desktop.")


if __name__ == "__main__":
    main()
