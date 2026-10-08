"""无视觉改绘：将生图 PNG 缩放并封装为 Windows 图标。"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
image = Image.open(ROOT / 'assets' / 'app-icon.png').convert('RGBA')
assert image.width == image.height, '应用图标必须为正方形'
assert image.getextrema()[3][0] == 0, '保留透明圆角'
sizes = [(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
image.save(ROOT / 'assets' / 'app-icon.ico', sizes=sizes)
for n in (24, 32, 64):
    image.resize((n, n), Image.Resampling.LANCZOS).save(ROOT / 'assets' / f'app-icon-{n}.png')
ico = Image.open(ROOT / 'assets' / 'app-icon.ico')
assert set(ico.ico.sizes()) == set(sizes)
print('ICO sizes:', ', '.join(str(n[0]) for n in sizes))
print('PNG master:', image.size, 'alpha:', image.getextrema()[3])
