import os
import sys
from pathlib import Path

from .config import logger


def _configure_tk_libraries() -> None:
    if not getattr(sys, "frozen", False):
        return

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass))

    executable = Path(sys.executable).resolve()
    if len(executable.parents) >= 2:
        contents_dir = executable.parents[1]
        candidates.append(contents_dir / "Resources")
        candidates.append(contents_dir / "Frameworks")

    for root in candidates:
        tcl_dir = root / "tcl9.0"
        tk_dir = root / "tk9.0"
        if tcl_dir.is_dir() and tk_dir.is_dir():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            logger.info("Configured Tcl/Tk paths from %s", root)
            return

    logger.warning("Could not locate bundled Tcl/Tk directories")


def run() -> int:
    _configure_tk_libraries()

    try:
        import customtkinter  # noqa: F401
        from .ui import App
        logger.info("customtkinter imported successfully")
    except ImportError as e:
        logger.critical(f"customtkinter not found: {e}")
        print("Установите зависимости:\n  pip install customtkinter PySocks")
        return 1

    try:
        logger.info("Starting ProxySwitch")
        App().mainloop()
        return 0
    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        try:
            from tkinter import messagebox

            messagebox.showerror("Критическая ошибка", f"Неожиданная ошибка: {e}")
        except Exception:
            print(f"Критическая ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
