import ctypes
from PIL import Image

def window_image(target):
    """PrintWindow 只截本窗口，避免其他应用遮挡或混入画面。"""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    for fun in (u.GetDC, u.GetAncestor, g.CreateCompatibleDC,
                g.CreateCompatibleBitmap, g.SelectObject):
        fun.restype = ctypes.c_void_p
    u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    u.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    g.DeleteObject.argtypes = [ctypes.c_void_p]
    g.DeleteDC.argtypes = [ctypes.c_void_p]
    u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    w, h = target.winfo_width(), target.winfo_height()
    hwnd = u.GetAncestor(target.winfo_id(), 2)
    screen = u.GetDC(None)
    dc = g.CreateCompatibleDC(screen)
    bitmap = g.CreateCompatibleBitmap(screen, w, h)
    old = g.SelectObject(dc, bitmap)
    try:
        assert u.PrintWindow(target.winfo_id(), dc, 3)
        import struct
        info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0))
        data = ctypes.create_string_buffer(w*h*4)
        assert g.GetDIBits(dc, bitmap, 0, h, data, info, 0)
        result = Image.frombytes('RGB', (w, h), data.raw, 'raw', 'BGRX').convert('RGBA')
        if result.convert('RGB').getbbox() is None:
            # DWM 圆角/分层窗口不响应 WM_PRINT 时，最小范围截取本窗口。
            from PIL import ImageGrab
            x, y = target.winfo_rootx(), target.winfo_rooty()
            result = ImageGrab.grab(bbox=(x, y, x+w, y+h)).convert('RGBA')
        # 使用窗口真实的可见区域导出透明圆角，不截取其他应用的内容。
        g.CreateRectRgn.argtypes = [ctypes.c_int] * 4
        g.CreateRectRgn.restype = ctypes.c_void_p
        u.GetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.GetRegionData.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        region = g.CreateRectRgn(0, 0, 0, 0)
        try:
            if u.GetWindowRgn(hwnd, region):
                size = g.GetRegionData(region, 0, None)
                region_data = ctypes.create_string_buffer(size)
                g.GetRegionData(region, size, region_data)
                header = struct.unpack('<IIIIiiii', region_data.raw[:32])
                from PIL import ImageDraw
                mask = Image.new('L', (w, h), 0)
                draw = ImageDraw.Draw(mask)
                for i in range(header[2]):
                    l, t, r, b = struct.unpack_from('<iiii', region_data.raw, 32+i*16)
                    draw.rectangle((l, t, r-1, b-1), fill=255)
                result.putalpha(mask)
        finally:
            g.DeleteObject(region)
        return result
    finally:
        g.SelectObject(dc, old)
        g.DeleteObject(bitmap)
        g.DeleteDC(dc)
        u.ReleaseDC(None, screen)
