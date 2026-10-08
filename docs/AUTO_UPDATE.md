# Windows 安装版自动更新

v1.1.1 为安装版增加自动下载和一键覆盖升级。v1.0.5、v1.1.0 只有检查与提示，需要先安装一次 v1.1.1。

1. 启动时读取本仓库最新正式 Release。版本更高且安装包已上传、校验信息完整时，显示新版本。
2. 安装版默认后台下载到用户本地缓存。用户可以取消，设置中也可以关闭自动下载。源码和便携版打开发布下载页。
3. 下载先写 `.part`，核对文件大小和 GitHub SHA-256 后才转为可安装文件；已有缓存同样重新校验。
4. 用户点击「重启并更新」后，保存当前会话。翻译、录音或保存失败会阻止更新。
5. 启动 Inno Setup，传入当前安装路径与旧程序 PID。安装器等待旧 PID 退出再覆盖，并在成功后自动打开新版。

更新目标由运行中 EXE 与本应用卸载注册项交叉确认。保持同一个 AppId，因此升级覆盖原目录，已有桌面快捷方式继续有效。更新不修改配置和会话目录。安装不会要求重启 Windows，也不会强制结束其他程序。

`src/app_updates.py` 提供元数据解析、安装目录识别、下载和校验；前端通过队列更新进度。安装等待与启动新版的代码位于 `installer.iss`。

```powershell
python tests/test_updates.py
python tests/check_update_ui.py
```

下载安装的命令参数和静默运行规则参考 Inno Setup 官方文档：[Setup 参数](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)、[Run 节](https://jrsoftware.org/ishelp/topic_runsection.htm)。
