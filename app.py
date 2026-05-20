# app.py
import ttkbootstrap as ttk
from ui.main_window import MainWindow


def main() -> None:
    root = ttk.Window(themename="cosmo")
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
