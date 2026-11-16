import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree.ElementTree import Element, SubElement, tostring

from install import ROOT, WORK, build_package
import pefile


def encode(data):
    return base64.b64encode(data).decode('ascii')


def engine_patch(original, modified, variant):
    if len(original) != len(modified):
        raise ValueError('The executable patch must preserve file size')
    pe = pefile.PE(data=original, fast_load=True)
    patch = Element('EnginePatch', variant=variant, length=str(len(original)))
    # Require the original PE layout, then check each patch site before writing to it.
    SubElement(patch, 'Header').text = encode(original[:pe.OPTIONAL_HEADER.SizeOfHeaders])
    spans = []
    for offset, (before, after) in enumerate(zip(original, modified)):
        if before == after:
            continue
        if spans and offset - spans[-1][1] <= 16:
            spans[-1][1] = offset + 1
        else:
            spans.append([offset, offset + 1])
    if not spans:
        raise ValueError('Executable patch is empty')
    for start, end in spans:
        SubElement(patch, 'Change', offset=str(start), before=encode(original[start:end]),
                   after=encode(modified[start:end]))
    return tostring(patch, encoding='utf-8', xml_declaration=True)


def export(game, variant, release=False):
    output, title = build_package(game, variant)
    folder = output / title
    engine = 'gamemd.exe' if variant == 'YR' else 'game.exe'
    state_path = game / 'StartAttackMOD' / f'state-{variant}.json'
    state = json.loads(state_path.read_text(encoding='utf-8-sig')) if state_path.exists() else None
    original = Path(state['backupDirectory']) / engine if state and state['active'] else game / engine
    patch = engine_patch(original.read_bytes(), (folder / engine).read_bytes(), variant)
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework/v3.5/csc.exe'
    if not compiler.is_file():
        raise FileNotFoundError('构建离线包需要构建机启用 .NET Framework 3.5（缺少 v3.5\\csc.exe）')
    installer = WORK / 'StartAttack-Win7.exe'
    subprocess.run([
        str(compiler), '/nologo', '/target:winexe', '/platform:x86', '/optimize+',
        '/codepage:65001', '/reference:System.Web.Extensions.dll',
        f'/resource:{ROOT / "管理MOD.ps1"},ManageMod', f'/out:{installer}',
        str(ROOT / 'Win7Installer.cs'),
    ], check=True)
    destination = WORK / f'StartAttack-Win7-{variant}{"-Patch" if release else ""}.zip'
    resources = None
    if release:
        from release_resources import release_resources
        resources = release_resources(game, variant, folder)
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as bundle:
        bundle.write(installer, installer.name)
        bundle.writestr('EnginePatch.xml', patch)
        bundle.writestr('Win7.md', (ROOT / 'Win7.md').read_text(encoding='utf-8-sig').encode('utf-8-sig'))
        bundle.write(folder / 'sgsticon.shp', 'Payload/sgsticon.shp')
        if release:
            bundle.writestr('Resources.xml', resources)
        else:
            suffix = 'md' if variant == 'YR' else ''
            for filename in (f'rules{suffix}.ini', f'ai{suffix}.ini', f'art{suffix}.ini',
                             f'ra2{suffix}.csf', 'gastrt.shp', 'ggstrt.shp'):
                bundle.write(folder / filename, f'Payload/{filename}')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export an offline Start Attack MOD package for Windows 7')
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--variant', choices=('YR', 'RA2'), required=True)
    parser.add_argument('--release', action='store_true', help='Export a patch-only package for distribution')
    args = parser.parse_args()
    print('Win7 离线包：', export(args.game.resolve(strict=True), args.variant, args.release))
