"""Native, explicit Windows folder selection; no unrestricted path API."""
import json
import os
import subprocess
from pathlib import Path


def folder_roots():
    if os.name == 'nt':
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [Path(chr(65 + i) + ':\\') for i in range(26) if mask & (1 << i)]
    # Development on Linux stays inside the project; never browse the host filesystem.
    return [Path(__file__).resolve().parents[1]]


def browse_folders(body):
    """List only directory names after an explicit same-origin browse request."""
    from server import Problem
    raw = body.get('path')
    roots = folder_roots()
    if raw is None or raw == '':
        return {'path': '', 'parent': None, 'folders': [{'name': str(p), 'path': str(p)} for p in roots], 'truncated': False}
    if not isinstance(raw, str) or len(raw) > 4096 or '\x00' in raw:
        raise Problem('文件夹路径无效。')
    path = Path(raw.strip().strip('"'))
    if not path.is_absolute():
        raise Problem('请选择完整的文件夹路径。')
    try:
        path = path.resolve(strict=True)
        if os.name != 'nt' and not any(path.is_relative_to(p.resolve()) for p in roots):
            raise Problem('只能浏览当前项目中的文件夹。', 403)
        if not path.is_dir():
            raise Problem('这不是文件夹。')
        folders = []
        truncated = False
        with os.scandir(path) as children:
            for child in children:
                try:
                    if child.is_symlink() or not child.is_dir(follow_symlinks=False):
                        continue
                    if getattr(child.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:
                        continue
                    if len(folders) == 500:
                        truncated = True
                        break
                    folders.append({'name': child.name, 'path': str(path / child.name)})
                except OSError:
                    continue
        folders.sort(key=lambda item: item['name'].casefold())
        parent = str(path.parent) if path.parent != path and path not in roots else None
        return {'path': str(path), 'parent': parent, 'folders': folders, 'truncated': truncated}
    except (OSError, RuntimeError):
        raise Problem('无法打开这个文件夹，请检查路径或访问权限。') from None


def choose_folder():
    from server import Problem
    if os.name != 'nt':
        raise Problem('自动相册需要在 Windows 电脑上运行；当前可以批量选择截图。')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(Path(__file__).with_name('select-folder.ps1'))], capture_output=True, timeout=180)
        if result.returncode: raise ValueError()
        value = json.loads(result.stdout.decode('utf-8-sig').strip())
        return Path(value['path']).resolve() if value.get('path') else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise Problem('文件夹选择未完成，请重试。')
