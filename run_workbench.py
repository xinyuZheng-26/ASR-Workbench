"""PyInstaller entry point; kept at repository root to preserve package imports."""

import multiprocessing

from asr_workbench.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
