"""确认 EXE 内嵌的每个尺寸都是最后选定的 ICO，而非缓存的旧图。"""
import hashlib
import sys
from pathlib import Path
import pefile
from PyInstaller.utils.win32.icon import IconFile

root = Path(__file__).resolve().parents[2]
ico = root / 'assets' / 'app-icon.ico'
exe = root / (sys.argv[1] if len(sys.argv) > 1 else 'dist/icon-refresh/pretend-foreigner/pretend-foreigner.exe')
expected = {hashlib.sha256(data).digest() for data in IconFile(str(ico)).images}
pe = pefile.PE(str(exe))
actual = set()
for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    if entry.id != 3:  # RT_ICON
        continue
    for resource in entry.directory.entries:
        for language in resource.directory.entries:
            data = language.data.struct
            actual.add(hashlib.sha256(pe.get_data(data.OffsetToData, data.Size)).digest())
assert actual == expected, 'EXE 图标与最终 ICO 不一致'
bundle = exe.parent / '_internal' / 'assets'
for source in (root / 'assets').glob('app-icon*'):
    assert (bundle / source.name).read_bytes() == source.read_bytes(), source.name
print('Verified EXE icon resources:', len(actual), 'sizes; bundled PNG/ICO match the final assets.')
