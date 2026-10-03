from pathlib import Path
import argparse
import contextlib
import io
import json
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).parent
WORK = ROOT / '_build'

try:
    import ra2mix
    import ra2csf
    import pefile
    import capstone
except ImportError as error:
    raise SystemExit(f'缺少 Python 依赖：{error.name}。先执行 python -m pip install -r requirements.txt') from error

import build_mod
from patch_money_slider import build as patch_executable, verify as verify_executable
from patch_ra2_money_slider import build as patch_ra2_executable, verify as verify_ra2_executable


def mix_file(path, nested=None):
    if not path.is_file():
        raise FileNotFoundError(f'缺少游戏资源：{path}')
    with contextlib.redirect_stdout(io.StringIO()):
        contents = ra2mix.read(mix_data=path.read_bytes())
        if nested:
            contents = ra2mix.read(mix_data=contents[nested])
    return contents


def extract_stock(game, variant, source):
    source.mkdir(parents=True, exist_ok=True)
    graphics = source / '图形'
    graphics.mkdir(exist_ok=True)
    ra2 = mix_file(game / 'ra2.mix')
    local = mix_file(game / 'ra2.mix', 'local.mix')
    for name in ['rules.ini', 'ai.ini', 'art.ini']:
        (source / name).write_bytes(local[name])
    def original_csf(name, mix_name, state_name):
        state_file = game / 'StartAttackMOD' / f'state-{state_name}.json'
        state = json.loads(state_file.read_text(encoding='utf-8-sig')) if state_file.exists() else None
        original = Path(state['backupDirectory']) / name if state and state['active'] else game / name
        return original.read_bytes() if original.is_file() else mix_file(game / mix_name)[name]

    (source / 'ra2.csf').write_bytes(original_csf('ra2.csf', 'language.mix', 'RA2'))
    cache = mix_file(game / 'ra2.mix', 'cache.mix')
    (graphics / 'cameo.pal').write_bytes(cache['cameo.pal'])
    generic = mix_file(game / 'ra2.mix', 'generic.mix')
    snow = mix_file(game / 'ra2.mix', 'snow.mix')
    (graphics / 'ggpowr.shp').write_bytes(generic['ggpowr.shp'])
    (graphics / 'gapowr.shp').write_bytes(snow['gapowr.shp'])
    if variant == 'YR':
        local_md = mix_file(game / 'ra2md.mix', 'localmd.mix')
        for name in ['rulesmd.ini', 'aimd.ini', 'artmd.ini']:
            (source / name).write_bytes(local_md[name])
        (source / 'ra2md.csf').write_bytes(original_csf('ra2md.csf', 'langmd.mix', 'YR'))


def build_package(game, variant):
    source = WORK / '基础资源'
    output = WORK / '安装文件'
    extract_stock(game, variant, source)
    build_mod.GAME = game
    build_mod.SOURCE = source
    build_mod.OUTPUT = output
    build_mod.ROOT = WORK
    title = '尤里的复仇' if variant == 'YR' else '原版红警2'
    build_mod.build((title,))
    target = output / title
    shutil.copy2(ROOT / 'assets' / 'sgsticon.shp', target / 'sgsticon.shp')
    cameo = (target / 'sgsticon.shp').read_bytes()
    assert struct.unpack_from('<4H', cameo) == (0, 60, 48, 1) and len(cameo) == 2912
    rules = build_mod.ini((target / ('rulesmd.ini' if variant == 'YR' else 'rules.ini')).read_bytes().decode('latin1'))
    assert rules['MultiplayerDialogSettings']['MinMoney'] == '5000'
    assert rules['MultiplayerDialogSettings']['MaxMoney'] == '500000'
    assert rules['SGSTART']['BuildCat'] == 'Tech'
    if variant == 'YR':
        state_file = game / 'StartAttackMOD' / 'state-YR.json'
        state = json.loads(state_file.read_text(encoding='utf-8-sig')) if state_file.exists() else None
        original = Path(state['backupDirectory']) / 'gamemd.exe' if state and state['active'] else game / 'gamemd.exe'
        patch_executable(original, target / 'gamemd.exe')
        print(verify_executable(target / 'gamemd.exe'))
    else:
        state_file = game / 'StartAttackMOD' / 'state-RA2.json'
        state = json.loads(state_file.read_text(encoding='utf-8-sig')) if state_file.exists() else None
        original = Path(state['backupDirectory']) / 'game.exe' if state and state['active'] else game / 'game.exe'
        patch_ra2_executable(original, target / 'game.exe')
        print(verify_ra2_executable(target / 'game.exe'))
    return output, title


def repair_saved_credits(game, variant):
    settings = game / ('RA2MD.INI' if variant == 'YR' else 'RA2.INI')
    if not settings.exists():
        return
    text = settings.read_bytes().decode('latin1')
    if '[Skirmish]' not in text:
        return
    start, end = build_mod.section_span(text, 'Skirmish')
    value = build_mod.ini(text)['Skirmish'].get('Credits')
    if value is None or 5000 <= int(value) <= 500000:
        return
    saved = game / 'StartAttackMOD' / '更新时保存'
    saved.mkdir(parents=True, exist_ok=True)
    backup = saved / f"{settings.stem}-before-credit-fix-{datetime.now():%Y%m%d-%H%M%S}.ini"
    if backup.exists():
        raise FileExistsError(backup)
    shutil.copy2(settings, backup)
    section, count = re.subn(r'(?m)^Credits=[^\r\n]*', 'Credits=10000', text[start:end])
    assert count == 1
    settings.write_bytes((text[:start] + section + text[end:]).encode('latin1'))
    print('遭遇战上次资金超出范围，已恢复为 10000；旧设置保存在', backup)


def install(game, variant, output, title):
    managed = game / 'StartAttackMOD'
    script = managed / '管理MOD.ps1'
    state = managed / f'state-{variant}.json'
    if state.exists() and json.loads(state.read_text(encoding='utf-8-sig'))['active']:
        if not script.exists():
            raise FileNotFoundError('现有 MOD 正在启用，但管理脚本缺失')
        subprocess.run(['pwsh', '-NoProfile', '-File', str(script), '-Action', 'Disable',
                        '-Variant', variant, '-GameDirectory', str(game)], check=True)
    managed.mkdir(exist_ok=True)
    shutil.copy2(ROOT / '管理MOD.ps1', script)
    destination = managed / '安装文件' / title
    destination.mkdir(parents=True, exist_ok=True)
    for file in (output / title).iterdir():
        shutil.copy2(file, destination / file.name)
    subprocess.run(['pwsh', '-NoProfile', '-File', str(script), '-Action', 'Enable',
                    '-Variant', variant, '-GameDirectory', str(game)], check=True)
    repair_saved_credits(game, variant)
    return managed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build and install Start Attack MOD from your local game files')
    parser.add_argument('--game', type=Path, required=True, help='RA2 or Yuri game folder')
    parser.add_argument('--variant', choices=['YR', 'RA2'], default='YR')
    parser.add_argument('--build-only', action='store_true', help='Prepare package without changing game files')
    options = parser.parse_args()
    game_dir = options.game.resolve(strict=True)
    out, name = build_package(game_dir, options.variant)
    if options.build_only:
        print('补丁已生成：', out / name)
    else:
        print('MOD 已安装：', install(game_dir, options.variant, out, name))
