"""Separate-process local editor fixture: accepts commands over stdin, reports stdout."""
import json
import os
import queue
import sys
import threading
import tkinter as tk

root = tk.Tk()
root.title('NeoHotaru 原输入框测试')
root.geometry('580x260+60+80')
root.attributes('-topmost', True)
tk.Label(root, text='仅用于本地回填测试，不发送消息', font=('Microsoft YaHei UI', 12)).pack(pady=12)
field = tk.Text(root, height=4, font=('Microsoft YaHei UI', 14), exportselection=False)
field.pack(fill='x', padx=15)
second = tk.Entry(root, font=('Microsoft YaHei UI', 12))
second.pack(fill='x', padx=15, pady=12)
commands = queue.Queue()
returns = 0

def output(kind, **extra):
    print(json.dumps(dict(kind=kind, value=field.get('1.0', 'end-1c'), returns=returns,
                         selection=[str(i) for i in field.tag_ranges('sel')],
                         second=second.get(),
                         insert=field.index('insert'), focus=str(root.focus_get()),
                         pid=os.getpid(), click=[root.winfo_rootx()+30,root.winfo_rooty()+15], **extra), ensure_ascii=True), flush=True)

def returned(event):
    global returns
    returns += 1
    output('changed')
    return 'break'

field.bind('<Return>', returned)

def reader():
    for line in sys.stdin:
        commands.put(json.loads(line))

threading.Thread(target=reader, daemon=True).start()

def poll():
    try:
        while True:
            cmd = commands.get_nowait()
            if cmd['action'] == 'prepare':
                field.delete('1.0', 'end')
                field.insert('1.0', cmd.get('value', '保留前缀｜替换这一段'))
                field.tag_add('sel', '1.5', 'end-1c')
                field.mark_set('insert', '1.5')
                root.lift();root.focus_force();field.focus_set()
                root.update()
                output('prepared', hwnd=root.winfo_id())
            elif cmd['action'] == 'second':
                root.lift();root.focus_force();second.focus_set();root.update()
                output('second')
            elif cmd['action'] == 'read':
                output('read')
            elif cmd['action'] == 'quit':
                root.destroy()
                return
    except queue.Empty:
        pass
    root.after(30, poll)

root.after(20, lambda: output('ready'))
root.after(30, poll)
root.mainloop()
