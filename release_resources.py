import base64
from difflib import SequenceMatcher
from mmap import ACCESS_READ, mmap
from xml.etree.ElementTree import Element, SubElement, tostring

from install import WORK, mix_file


def encode(data):
    return base64.b64encode(data).decode('ascii')


def archive_entry(game, archive, contents, entry):
    with (game / archive).open('rb') as handle, mmap(handle.fileno(), 0, access=ACCESS_READ) as data:
        offset = data.find(contents)
        if offset < 0:
            raise ValueError(f'{entry} not found in {archive}')
        file = Element('Resource', name=entry, archive=archive, offset=str(offset),
                       length=str(len(contents)), archiveLength=str(len(data)))
    for position in (0, len(contents) // 2, len(contents) - 24):
        SubElement(file, 'Guard', offset=str(position)).text = encode(contents[position:position + 24])
    return file


def line_changes(file, before, after):
    old = before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    offsets = [0]
    for line in old:
        offsets.append(offsets[-1] + len(line))
    for kind, start, end, new_start, new_end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if kind == 'equal':
            SubElement(file, 'Copy', offset=str(offsets[start]), length=str(offsets[end] - offsets[start]))
        else:
            if kind != 'insert':
                # Confirm the original text at each edited range, without publishing whole files.
                SubElement(file, 'Guard', offset=str(offsets[start])).text = encode(before[offsets[start]:min(offsets[end], offsets[start] + 24)])
            if kind != 'delete':
                SubElement(file, 'Add').text = encode(b''.join(new[new_start:new_end]))


def release_resources(game, variant, folder):
    suffix = 'md' if variant == 'YR' else ''
    source = WORK / '基础资源'
    root = Element('Resources')
    for stem in ('ai', 'rules', 'art'):
        name = f'{stem}{suffix}.ini'
        original = (source / name).read_bytes()
        file = archive_entry(game, f'ra2{suffix}.mix', original, name)
        line_changes(file, original, (folder / name).read_bytes())
        root.append(file)
    for name in ('gastrt.shp', 'ggstrt.shp'):
        original = (source / '图形' / name.replace('strt', 'powr')).read_bytes()
        root.append(archive_entry(game, 'ra2.mix', original, name))
    name = f'ra2{suffix}.csf'
    archive = 'langmd.mix' if suffix else 'language.mix'
    csf = archive_entry(game, archive, mix_file(game / archive)[name], name)
    csf.set('appendLabel', 'Name:SGSTART')
    csf.set('labelText', '开始进攻')
    root.append(csf)
    return tostring(root, encoding='utf-8', xml_declaration=True)
