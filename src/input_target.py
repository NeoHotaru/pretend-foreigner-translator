"""Capture the active Windows input destination and insert Unicode on confirmation.

Only an explicit shortcut captures a target. No key listener or clipboard access.
"""
import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

WM_GETTEXT = 0x000D
GA_ROOT = 2
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


class TargetError(RuntimeError):
    pass


class PartialInsertError(TargetError):
    """Some events were delivered; never retry the whole text automatically."""


class GUIThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyboardInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]


def user32():
    if os.name != "nt":
        raise TargetError("翻译输入目前仅支持 Windows")
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUIThreadInfo)]
    u.GetGUIThreadInfo.restype = wintypes.BOOL
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    u.SendInput.restype = wintypes.UINT
    return u


def window_text(u, hwnd):
    buf = ctypes.create_unicode_buffer(4096)
    u.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def gui_info(u, hwnd):
    tid = u.GetWindowThreadProcessId(hwnd, None)
    info = GUIThreadInfo(cbSize=ctypes.sizeof(GUIThreadInfo))
    if not tid or not u.GetGUIThreadInfo(tid, ctypes.byref(info)):
        raise TargetError("没能确定输入位置，请点一下原输入框再唤起")
    return info


@dataclass(frozen=True)
class InputTarget:
    window: int
    focus: int
    process_id: int
    title: str
    position: tuple
    caret: int = 0

    def validate(self, u=None):
        u = u or user32()
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(self.window, ctypes.byref(pid))
        if not u.IsWindow(self.window) or pid.value != self.process_id:
            raise TargetError("原窗口已关闭，请重新选择输入位置")
        if not u.IsWindow(self.focus) or not u.IsWindowVisible(self.window):
            raise TargetError("原输入位置已不可用，请重新唤起")
        if window_text(u, self.window) != self.title:
            raise TargetError("原窗口内容已切换，请重新选择输入位置")


def capture_target():
    u = user32()
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        raise TargetError("先点目标输入框，再按翻译输入快捷键")
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        raise TargetError("先点要填入文字的输入框，再按翻译输入快捷键")
    info = gui_info(u, hwnd)
    focus = info.hwndFocus
    if not focus or u.GetAncestor(focus, GA_ROOT) != hwnd:
        raise TargetError("先点目标输入框，再按翻译输入快捷键")
    class_name = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(focus, class_name, len(class_name))
    if "edit" in class_name.value.lower() and u.GetWindowLongW(focus, -16) & 0x20:
        raise TargetError("请选择普通文本输入框")
    point = wintypes.POINT()
    if info.hwndCaret:
        point.x, point.y = info.rcCaret.left, info.rcCaret.bottom
        u.ClientToScreen(info.hwndCaret, ctypes.byref(point))
    else:
        u.GetCursorPos(ctypes.byref(point))
    return InputTarget(int(hwnd), int(focus), pid.value, window_text(u, hwnd),
                       (point.x, point.y), int(info.hwndCaret or 0))


def modifiers_released():
    u = user32()
    return not any(u.GetAsyncKeyState(vk) & 0x8000 for vk in VK_MODIFIERS)


def restore_target(target):
    u = user32()
    target.validate(u)
    u.ShowWindow(target.window, 9)
    if u.GetForegroundWindow() != target.window:
        u.SetForegroundWindow(target.window)
    return u.GetForegroundWindow() == target.window


def target_has_focus(target):
    u = user32()
    target.validate(u)
    info = gui_info(u, target.window)
    return (u.GetForegroundWindow() == target.window and info.hwndFocus == target.focus
            and (not target.caret or info.hwndCaret == target.caret))


def insert_text(target, text):
    if not text:
        raise TargetError("没有可填入的译文")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise TargetError("多行或含控制字符的译文，请复制后手动粘贴以保留格式。")
    u = user32()
    if not target_has_focus(target):
        raise TargetError("输入位置已改变，请重新点原输入框并唤起")
    if not modifiers_released():
        raise TargetError("请松开快捷键后再填入")
    # VK_PACKET emits UTF-16 characters, respecting the destination selection.
    # It neither replaces the clipboard nor emits Enter/Tab keyboard commands.
    raw = text.encode("utf-16-le")
    units = [int.from_bytes(raw[i:i+2], "little") for i in range(0, len(raw), 2)]
    events = (Input * (2 * len(units)))()
    for i, unit in enumerate(units):
        for offset, flags in [(0, KEYEVENTF_UNICODE), (1, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]:
            events[2*i+offset].type = 1
            events[2*i+offset].ki = KeyboardInput(0, unit, flags, 0, 0)
    count = u.SendInput(len(events), events, ctypes.sizeof(Input))
    if count == 0:
        raise TargetError("没能填入；可以复制译文后手动粘贴。管理员窗口可能无法回填")
    if count != len(events):
        raise PartialInsertError("填入未完成，请检查原输入框；本次不会自动重试")


def ime_is_composing(hwnd):
    if os.name != "nt":
        return False
    imm = ctypes.WinDLL("imm32", use_last_error=True)
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmGetCompositionStringW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    imm.ImmGetCompositionStringW.restype = wintypes.LONG
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    context = imm.ImmGetContext(hwnd)
    if not context:
        return False
    try:
        return imm.ImmGetCompositionStringW(context, 0x0008, None, 0) > 0
    finally:
        imm.ImmReleaseContext(hwnd, context)
