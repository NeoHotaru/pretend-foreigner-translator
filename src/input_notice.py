"""Small non-activating status message beside the original input."""
import ctypes
import tkinter as tk
from ctypes import wintypes
from island_window import work_area
from ui_kit import C_BG as ISLAND_BG, C_TEXT as ISLAND_TEXT, C_MUTED as ISLAND_MUTED, FONT_UI, FONT_SMALL, C_BAD


def show_nonactivating(window, x, y, width, height, radius=0):
    window.geometry('%dx%d+%d+%d' % (width, height, x, y))
    window.update_idletasks()
    u = ctypes.windll.user32
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    hwnd = u.GetAncestor(window.winfo_id(), 2)
    get_style = u.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p)==8 else u.GetWindowLongW
    set_style = u.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p)==8 else u.SetWindowLongW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style(hwnd, -20, get_style(hwnd, -20) | 0x08000000 | 0x80)
    if radius:
        g = ctypes.windll.gdi32
        g.CreateRoundRectRgn.argtypes = [ctypes.c_int]*6
        g.CreateRoundRectRgn.restype = wintypes.HANDLE
        g.DeleteObject.argtypes = [wintypes.HANDLE]
        u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        region = g.CreateRoundRectRgn(0, 0, width+1, height+1, radius*2, radius*2)
        if region and not u.SetWindowRgn(hwnd, region, True):
            g.DeleteObject(region)
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, width, height, 0x10 | 0x40)


def hide_nonactivating(window):
    from input_target import user32
    u = user32()
    u.ShowWindow(u.GetAncestor(window.winfo_id(), 2), 0)
    window.withdraw()


class InputNotice(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=ISLAND_BG)
        self.title('假装外国人 · 输入框翻译状态')
        self._timer = None
        body = tk.Frame(self, bg=ISLAND_BG, padx=16, pady=12)
        body.pack(fill='both', expand=True)
        self.heading = tk.Label(body, text='输入框翻译', bg=ISLAND_BG, fg=ISLAND_TEXT,
                                font=FONT_UI, anchor='w')
        self.heading.pack(fill='x')
        self.message = tk.Label(body, text='', bg=ISLAND_BG, fg=ISLAND_MUTED,
            font=FONT_SMALL, wraplength=320, justify='left', anchor='w')
        self.message.pack(fill='x', pady=(4, 0))

    def show(self, text, point=None, error=False, pending=False):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        self.heading.configure(text='翻译未完成' if error else '正在翻译…' if pending else '输入框翻译')
        self.message.configure(text=text, fg=C_BAD if error else ISLAND_MUTED)
        self.update_idletasks()
        point = point or (self.winfo_screenwidth()-380, self.winfo_screenheight()-150)
        left, top, right, bottom = work_area(*point, (self.winfo_screenwidth(), self.winfo_screenheight()))
        width, height = 354, max(82, self.winfo_reqheight())
        x = max(left+8, min(point[0], right-width-8))
        y = max(top+8, min(point[1]+24, bottom-height-8))
        # NOACTIVATE + SHOWWINDOW: never pull the user out of their editor.
        show_nonactivating(self, x, y, width, height, radius=14)
        if not pending:
            self._timer = self.after(7000 if error else 4000, self.hide)

    def hide(self):
        if self._timer:
            self.after_cancel(self._timer)
        self._timer = None
        hide_nonactivating(self)
