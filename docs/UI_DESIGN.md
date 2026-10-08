# 主界面与悬浮窗

这是一款伴随浏览器使用的桌面翻译工具。界面围绕两侧对话展开：输入原文、翻译、阅读与复制；会话和引擎留在侧栏，历史按需查看。

## 设计与字体

- 采用 Windows 自带的 Microsoft YaHei UI，避免新增字体下载和打包依赖。窗口标题 21pt、侧栏品牌 17pt、方向标题 13pt、主编辑区 12pt、控件 10pt、辅助说明 9pt。字体跟随 tkinter 的系统 DPI 缩放。
- 背景 `#f5f7fa`，编辑面板白色，文字 `#203247`，辅助文字 `#596b7d`。发送方向 `#2459a6`，接收方向 `#08796d`。颜色同时配有文字方向，避免仅靠颜色理解操作。
- 主界面使用稳定的侧栏、水平语言设置和双栏编辑区；译文旁放复制，输入后放翻译与语音。状态栏优先反馈“已复制”和耗时。
- 原文和译文可滚动，Tab 移到下一控件，Shift+Tab 返回；Ctrl+Enter 翻译。译文支持选中与 Ctrl+A / Ctrl+C，阻止粘贴改写。
- 记忆是非模态独立窗口。打开历史不会压缩主编辑区，仍可以对照原文和译文；保留多选删除、清空、复制和双击回填。
- 悬浮岛默认是 224×52 的深色胶囊，点击后从原位置展开成 420×600 的圆角面板。面板沿用系统字体、翻译方向颜色与应用图标，编辑区与译文区平分可用空间。拖动只绑定胶囊、标题和空白区域，会话菜单保持正常点击。
- 收起、Esc 和外部点击返回胶囊，内容保持；录音时 Esc 优先取消。胶囊反馈录音、翻译中和已复制，任务继续在后台进行。右键菜单提供隐藏、透明度、剪贴板翻译与返回主界面。
- 开合采用响应参数 0.3 秒、临界阻尼的原生弹簧；中途反向动作延续当前显示值和速度。Tk 不支持网页的 compositor transform，外层窗口改变尺寸，面板内容保持固定布局，动画稳定后再呈现。快捷键与减少动画设置使用即时切换，没有额外延迟。
- 圆角由 Windows 原生区域裁剪，角外透明并且不接收点击。只在外层窗口完成映射后设置区域；同一形状不重复设置。胶囊靠近屏幕底部时向上展开，所有形态限制在所在显示器工作区。

设计参考入口：[Readymag 的 Awwwards Honorable Mention 页面](https://www.awwwards.com/sites/readymag-4)、[Awwwards Typography 案例库](https://www.awwwards.com/inspiration/typography-longfellow)。本次借鉴字体层级、留白与对齐的思路，按桌面翻译任务自行安排布局。检索能确认案例条目，站点页面的直接抓取超时；没有按网页截图逐像素复刻。

## 验证与预览

```powershell
python selftest.py
python artifacts/ui-refresh/check_interactions.py
python artifacts/island-refresh/check_island.py
```

交互检查走真实 tkinter 主循环，以本地假响应替换网络请求；验证翻译、复制、错误重试、方向稳定、记忆、键盘操作及最小窗口布局。配置和会话写入沙箱，并比较真实用户数据的哈希。

悬浮岛检查覆盖 31 项用户路径，包括胶囊默认状态、真实圆角、主界面隐藏、可中断开合、拖动、边缘展开、焦点、Esc、草稿保留、减少动画与后台翻译。实际开合帧录制在 `artifacts/island-refresh/island.gif`。

预览生成器 `artifacts/ui-refresh/preview_ui.py` 支持 `main`、`small`、`overlay`、`memory`。截图来自实际 tkinter 窗口，预览内容是示例对话，不是用户历史。主界面与悬浮窗截图在 `docs/main-window.png` 和 `docs/overlay-window.png`。
