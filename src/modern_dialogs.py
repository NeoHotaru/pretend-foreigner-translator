"""Small text prompts using the app theme and native modal keyboard behavior."""
from tkinter import ttk, simpledialog
from ui_kit import C_BG, C_BAD


class TextPrompt(simpledialog.Dialog):
    def __init__(self, parent, title, prompt, initialvalue=''):
        self.prompt = prompt
        self.initialvalue = initialvalue
        super().__init__(parent, title)

    def body(self, master):
        self.configure(bg=C_BG)
        master.configure(bg=C_BG)
        body = ttk.Frame(master, padding=(20, 16, 20, 10))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=self.title(), style='Head.TLabel').pack(anchor='w')
        ttk.Label(body, text=self.prompt, style='Hint.TLabel', wraplength=380,
                  justify='left').pack(anchor='w', pady=(10, 16))
        self.entry = ttk.Entry(body, width=36)
        self.entry.insert(0, self.initialvalue)
        self.entry.pack(fill='x')
        self.entry.selection_range(0, 'end')
        self.hint = ttk.Label(body, text='', style='Hint.TLabel', foreground=C_BAD)
        self.hint.pack(anchor='w', pady=(6, 0))
        return self.entry

    def buttonbox(self):
        box = ttk.Frame(self, padding=(25, 0, 25, 20))
        box.pack(fill='x')
        ttk.Button(box, text='确定', style='Go.TButton', command=self.ok).pack(side='right')
        ttk.Button(box, text='取消', style='Quiet.TButton', command=self.cancel).pack(side='right', padx=8)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def validate(self):
        if self.entry.get().strip():
            return True
        self.hint.configure(text='请填写一个名字。')
        return False

    def apply(self):
        self.result = self.entry.get().strip()


def ask_text(title, prompt, *, parent, initialvalue=''):
    return TextPrompt(parent, title, prompt, initialvalue).result
