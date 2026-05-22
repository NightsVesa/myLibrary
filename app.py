# app.py
import ttkbootstrap as ttk
from tkinterdnd2 import TkinterDnD

from ui.main_window import MainWindow


def main() -> None:
    root = ttk.Window(themename="cosmo")
    # Enable drag-and-drop on the existing ttk root — adds the tkdnd hooks
    # without forcing us to switch the Tk class.
    root.TkdndVersion = TkinterDnD._require(root)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
