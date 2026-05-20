import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH

from config import APP_TITLE, WINDOW_GEOMETRY
from ui.input_tab import InputTab
from ui.upload_tab import UploadTab
from ui.search_tab import SearchTab


class MainWindow:
    def __init__(self, root: ttk.Window) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry(WINDOW_GEOMETRY)
        root.resizable(False, False)
        root.attributes("-topmost", True)  # Always on top — desktop pet behaviour
        root.overrideredirect(False)        # Keep OS chrome for now

        notebook = ttk.Notebook(root, bootstyle="primary")
        notebook.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self.input_tab = InputTab(notebook)
        self.upload_tab = UploadTab(notebook)
        self.search_tab = SearchTab(notebook)

        notebook.add(self.input_tab.frame, text="  ✍ 输入  ")
        notebook.add(self.upload_tab.frame, text="  📁 上传  ")
        notebook.add(self.search_tab.frame, text="  🔍 查询  ")
