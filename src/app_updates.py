# -*- coding: utf-8 -*-
"""Windows 安装版更新：GitHub 元数据、校验下载和 Inno Setup 交接。"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from translator_core import APP_VERSION, REPO_SLUG, parse_version

APP_ID = '{8E1C2A54-3B7D-4F6E-9A11-7C5D2E4B9F30}'


class UpdateError(Exception):
    pass


class DownloadCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    filename: str
    download_url: str
    size: int
    sha256: str


def parse_release(data, current_version=APP_VERSION):
    """只接受本仓库正式发布、名称与版本一致的安装包。"""
    if data.get('draft') or data.get('prerelease'):
        return None
    tag = str(data.get('tag_name') or '')
    match = re.fullmatch(r'v?(\d+\.\d+\.\d+)', tag)
    if not match:
        raise UpdateError('新版本信息不完整，请稍后重试')
    version = match.group(1)
    if parse_version(version) <= parse_version(current_version):
        return None
    release_url = 'https://github.com/%s/releases/tag/%s' % (REPO_SLUG, tag)
    name = 'pretend-foreigner-setup-%s.exe' % version
    expected_url = 'https://github.com/%s/releases/download/%s/%s' % (REPO_SLUG, tag, name)
    asset = next((a for a in data.get('assets', []) if a.get('name') == name), None)
    if asset is None or asset.get('state') != 'uploaded':
        raise UpdateError('新版本安装包尚未准备好，请稍后重试')
    if asset.get('browser_download_url') != expected_url:
        raise UpdateError('安装包下载地址与本项目不一致')
    digest = str(asset.get('digest') or '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise UpdateError('安装包缺少校验信息，请稍后重试')
    size = asset.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateError('安装包大小信息无效')
    return UpdateInfo(version, release_url, name, expected_url, size, digest[7:].lower())


def fetch_update(current_version=APP_VERSION, timeout=20):
    request = urllib.request.Request(
        'https://api.github.com/repos/%s/releases/latest' % REPO_SLUG,
        headers={'User-Agent': 'pretend-foreigner/%s' % APP_VERSION,
                 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return parse_release(data, current_version)
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError('检查更新失败，请检查网络后重试') from error


def registered_install_dirs():
    """只读本应用自己的卸载注册项，包含 32/64 位视图。"""
    if sys.platform != 'win32':
        return []
    import winreg
    found = []
    key_path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\%s_is1' % APP_ID
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    for name in ('InstallLocation', 'Inno Setup: App Path'):
                        try:
                            value, _ = winreg.QueryValueEx(key, name)
                            if value:
                                found.append(Path(value))
                        except OSError:
                            pass
            except OSError:
                pass
    return found


def installed_directory(executable=None, frozen=None, registered=None):
    """便携包和源码不走安装器覆盖，防止覆盖另一份已安装程序。"""
    if frozen is None:
        frozen = getattr(sys, 'frozen', False)
    if not frozen:
        return None
    executable = Path(executable or sys.executable).resolve()
    if executable.name.lower() != 'pretend-foreigner.exe':
        return None
    for directory in registered if registered is not None else registered_install_dirs():
        if os.path.normcase(str(Path(directory).resolve())) == os.path.normcase(str(executable.parent)):
            return executable.parent
    return None


def update_cache():
    return Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'pretend-foreigner' / 'updates'


def file_matches(path, info):
    try:
        if path.stat().st_size != info.size:
            return False
        with path.open('rb') as file:
            digest = hashlib.sha256()
            for chunk in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(chunk)
            return digest.hexdigest() == info.sha256
    except OSError:
        return False


def download_update(info, cache=None, progress=None, cancel=None, opener=None):
    # 即使调用者自行构造 UpdateInfo，也不允许其决定缓存外的路径。
    if info.filename != 'pretend-foreigner-setup-%s.exe' % info.version or not re.fullmatch(r'\d+\.\d+\.\d+', info.version):
        raise UpdateError('安装包名称无效')
    cache = Path(cache or update_cache())
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise UpdateError('更新下载目录无法写入，请检查磁盘空间和权限') from error
    target = cache / info.filename
    if file_matches(target, info):
        if progress:
            progress(info.size, info.size)
        return target
    temporary = cache / (info.filename + '.part')
    cancel = cancel or threading.Event()
    try:
        if cancel.is_set():
            raise DownloadCancelled('下载已取消')
        request = urllib.request.Request(info.download_url,
            headers={'User-Agent': 'pretend-foreigner/%s' % APP_VERSION})
        digest, downloaded = hashlib.sha256(), 0
        with (opener or urllib.request.urlopen)(request, timeout=30) as response, temporary.open('wb') as output:
            while True:
                if cancel.is_set():
                    raise DownloadCancelled('下载已取消')
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > info.size:
                    raise UpdateError('安装包大小不符，请重试下载')
                output.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(downloaded, info.size)
        if cancel.is_set():
            raise DownloadCancelled('下载已取消')
        if downloaded != info.size or digest.hexdigest() != info.sha256:
            raise UpdateError('安装包校验失败，请重试下载')
        temporary.replace(target)
        return target
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, UpdateError):
            raise
        raise UpdateError('下载中断，请检查网络后重试') from error


def launch_installer(info, package, executable=None, frozen=None, registered=None, parent_pid=None, runner=None):
    directory = installed_directory(executable, frozen, registered)
    if directory is None:
        raise UpdateError('当前不是安装版，请从下载页升级')
    package = Path(package).resolve()
    if not file_matches(package, info):
        raise UpdateError('安装包校验失败，请重新下载')
    # Inno Setup 等待旧 PID 退出后才复制；安装完成后由同一安装包启动新版。
    args = [str(package), '/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/DIR=%s' % directory,
            '/PFTUPDATE=1', '/PFTPID=%d' % (parent_pid or os.getpid()),
            '/LOG=%s' % (package.parent / ('install-%s.log' % info.version))]
    try:
        return (runner or subprocess.Popen)(args, cwd=str(package.parent),
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as error:
        raise UpdateError('无法启动更新安装包，请重试') from error
