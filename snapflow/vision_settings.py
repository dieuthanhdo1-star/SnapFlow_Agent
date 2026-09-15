"""Recover local model settings across release folders; never search arbitrary folders."""
import json
import os
from pathlib import Path
import urllib.parse

from providers.vlm_client import VLMClient

DIRECT = ('VISION_BASE_URL', 'VISION_API_KEY', 'VISION_MODEL')


def project_base(root):
    root = Path(root)
    if not root.name.startswith('SnapFlow-'):
        return root.parent
    while root.name.startswith('SnapFlow-'):
        root = root.parent
    return root


def direct_settings(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('VISION_DISABLED') == '1':
        return None
    if not all(isinstance(value.get(k), str) and value[k].strip() for k in DIRECT):
        return None
    url = urllib.parse.urlsplit(value['VISION_BASE_URL'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        return None
    return {k: value[k] for k in DIRECT}


def remember(root, settings=None, gateway=None, replace=False):
    """Keep credentials outside disposable release folders, with private file mode."""
    folder = project_base(root) / '.snapflow-config'
    path = folder / ('vision-private.json' if settings else 'api_key.json')
    if path.exists() and not replace:
        return
    value = {k: settings[k] for k in DIRECT} if settings else json.loads(Path(gateway).read_text(encoding='utf-8-sig'))
    folder.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.new')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def discover(root):
    root = Path(root)
    base = project_base(root)
    primary = list(dict.fromkeys([root, root.parent, base, base / '.snapflow-config']))
    invalid = False

    def read(folder):
        nonlocal invalid
        for path in [folder / 'vision-private.json', folder / 'data/vision-private.json', folder / 'api_key.json']:
            if not path.is_file():
                continue
            try:
                if path.name == 'api_key.json':
                    client = VLMClient(path)
                    return {}, path, (client.base, client.key, 'gemini-3.8-flash')
                value = direct_settings(path)
                if value:
                    return value, None, tuple(value[k] for k in DIRECT)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                invalid = True
        return None

    for folder in primary:
        value = read(folder)
        if value:
            return value[0], value[1], ''
    # Only recognized installations next to this one, including double ZIP extraction.
    installations = [base / 'snapflow']
    for folder in sorted(base.glob('SnapFlow-*'), reverse=True):
        if folder.is_dir() and not folder.is_symlink():
            installations.append(folder)
            installations.extend(folder.glob('SnapFlow-*'))
    found = []
    for folder in installations:
        if folder in primary or folder.is_symlink() or not (folder / 'server.py').is_file() or not (folder / 'launcher.py').is_file():
            continue
        value = read(folder)
        if value:
            found.append(value)
    if found:
        if len({v[2] for v in found}) > 1:
            return {}, None, '发现多个旧版识别配置，请在设置中确认要使用的配置。原配置未修改。'
        return found[0][0], found[0][1], ''
    if invalid:
        return {}, None, '找到了识别配置，但格式无法读取。请检查原来的配置文件，勿删除密钥。'
    return {}, None, '未找到本机识别配置。请将原来的 api_key.json 放到程序文件夹或其上一级，再重启；已有文件夹授权会保留。'
