import sys
from tkinter import messagebox

from .config import logger
from .ui import App


def run() -> int:
    try:
        import customtkinter  # noqa: F401
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
        messagebox.showerror("Критическая ошибка", f"Неожиданная ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
