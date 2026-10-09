# 应用图标

由内置 image_gen 工具生成。FAKE 贴纸覆在中文「中」字原稿上，掀起的贴纸一角露出中文，表达“给自己的话套上英文外衣”。蓝色呼应主界面，白色贴纸与黄色原稿让两层身份清晰可见。原始 PNG 的透明圆角保留，导出只做缩放与 ICO 格式封装。

- `app-icon.png`：生成原稿，1254×1254。
- `app-icon.ico`：Windows 图标，包含 16 / 20 / 24 / 32 / 40 / 48 / 64 / 128 / 256 像素。
- `app-icon-24.png`、`app-icon-32.png`、`app-icon-64.png`：界面和 Tk 窗口图标。

主窗口、子窗口、任务栏、侧栏品牌和悬浮窗使用这套资源；PyInstaller 将 assets 包含进程序，并把 ICO 写入 EXE。Inno Setup 使用相同 ICO。导出命令：`python artifacts/icon-refresh/export_icon.py`。

Windows 标题栏用 `iconbitmap(ico)` 显式设置当前窗口；每个 Tk/Toplevel 映射时同样设置，覆盖后续设置、记忆等窗口。仅设置 `iconbitmap(default=ico)` 在本机 Tk 中会令窗口的原生小图标和大图标为空。安装器快捷方式显式指定包内 ICO，避免继承旧 EXE 图标缓存。

## 生成提示词

Precise compositing correction to the attached existing FAKE / 中 application icon. Change ONLY the occlusion/layering at the letter E and the curled paper corner. The existing error is that the dark letter E is printed over the raised gray/white folded paper corner. Correct physical layer order: the word FAKE is ink printed ONLY on the flat front face of the white sticker; the lifted folded corner is in front of that ink and must visibly COVER the lower-right portion of the E where the E intersects the fold. The visible E must be clipped along the same diagonal/curved boundary as the flat white front sticker surface. NO dark E ink whatsoever on the gray curled underside of the fold or on the yellow underlying paper. The peeled white/gray corner should smoothly occlude the end of the E, with a clean, convincing interruption of the E's bottom/right strokes. Do NOT move, shrink, retype or reposition FAKE to avoid the overlap: maintain the current FAKE text's exact typography, scale, baseline, and placement, and only correct its clipping and occlusion. Preserve absolutely all other pixels and design elements as closely as possible: original blue rounded-square tile, all white and yellow paper shapes, existing curl geometry, the Chinese character 中 EXACTLY unchanged, all colors, composition, proportions, shadows, rounded corners and actual transparency outside the tile. Keep the image square. No extra text or marks. Only repair the physically incorrect letter-versus-paper layering.
