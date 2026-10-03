from pathlib import Path
import json
import struct
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / '工具依赖'))
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

BASE = 0x400000
CAVE = 0x7E0390
DIRECT = CAVE
DIALOG = CAVE + 0x80
RANGE_STUB = CAVE + 0x100
SORT_STUB = CAVE + 0x200
RANGE_MARKER = 0x53544753
RULES = 0x8871E0
SELECTED = 0xA8B25C
REGIONS = [(0x5B51F7, 0x5B521E, 'edi', DIRECT, False),
           (0x5B86B2, 0x5B86DF, 'edi', DIRECT, True),
           (0x5E3153, 0x5E317F, 'esi', DIALOG, False),
           (0x6AED12, 0x6AED34, 'esi', DIRECT, False)]
DISASM = Cs(CS_ARCH_X86, CS_MODE_32)


class Code:
    def __init__(self, address):
        self.address, self.data, self.labels, self.fixups = address, bytearray(), {}, []

    def emit(self, data):
        self.data.extend(data)

    def label(self, name):
        self.labels[name] = self.address + len(self.data)

    def jump(self, target, condition=None):
        self.emit(b'\xe9' if condition is None else b'\x0f' + bytes([condition]))
        self.fixups.append((len(self.data), target))
        self.emit(b'\0' * 4)

    def finish(self):
        for offset, target in self.fixups:
            destination = self.labels[target] if isinstance(target, str) else target
            struct.pack_into('<i', self.data, offset, destination - self.address - offset - 4)
        return bytes(self.data)


def helper(dialog):
    # PUSHAD preserves the caller's registers; the HWND argument lies above it.
    code = bytearray(b'\x60\x8b\x7c\x24\x24\x8b\x1d' + struct.pack('<I', RULES))
    # The game's custom slider supports 0x406 only. Our marker extends that
    # handler to read both DWORD limits directly from this RulesClass pointer.
    code += b'\x53\x68' + struct.pack('<I', RANGE_MARKER)
    code += b'\x68' + struct.pack('<I', 0x406)
    if dialog:
        code += b'\x68' + struct.pack('<I', 0x402)
    code += b'\x57\xff\x15' + struct.pack('<I', 0x7E1490 if dialog else 0x7E14A4)
    return bytes(code + b'\x61\xc2\x04\x00')


def range_stub():
    code = Code(RANGE_STUB)
    code.emit(b'\x8b\xac\x24\x60\x01\x00\x00')
    code.emit(b'\x81\xbc\x24\x5c\x01\x00\x00' + struct.pack('<I', RANGE_MARKER))
    code.jump('packed', 0x85)
    code.emit(b'\x8b\xb5\x80\x14\x00\x00\x8b\xad\x88\x14\x00\x00')
    code.jump('continue')
    code.label('packed')
    code.emit(b'\x8b\xf5\x81\xe6\xff\xff\x00\x00\xc1\xed\x10')
    code.label('continue')
    code.emit(b'\x2b\xee')
    code.jump(0x61E5AE)
    return code.finish()


def sort_stub():
    code = Code(SORT_STUB)
    code.emit(b'\x60\x8b\x44\x24\x34\x8b\x4c\x24\x38')
    for register, first, second, target, next_label in [
        ('eax', b'\x81\x78\x24', b'\x81\x78\x28', 'last', 'right'),
        ('ecx', b'\x81\x79\x24', b'\x81\x79\x28', 'first', 'normal')]:
        code.emit(b'\x85\xc0' if register == 'eax' else b'\x85\xc9')
        code.jump(next_label, 0x84)
        code.emit(first + b'SGST')
        code.jump(next_label, 0x85)
        code.emit(second + b'ART\0')
        code.jump(target, 0x84)
        code.label(next_label)
    # Preserve the native order for every other item.
    code.emit(b'\x61\x83\xfe\x1f')
    code.jump(0x6A8477, 0x84)
    code.jump(0x6A8468)
    code.label('last')
    code.emit(b'\x61')
    code.jump(0x6A86A0)
    code.label('first')
    code.emit(b'\x61')
    code.jump(0x6A8692)
    return code.finish()


def redirect(start, end, destination):
    return b'\xe9' + struct.pack('<i', destination-start-5) + b'\x90' * (end-start-5)


def hook(start, end, register, dest, selected):
    code = bytearray(b'\x8b\x2d' + struct.pack('<I', SELECTED) if selected else b'')
    code += b'\x57' if register == 'edi' else b'\x56'
    call_address = start + len(code)
    code += b'\xe8' + struct.pack('<i', dest - call_address - 5)
    return bytes(code + b'\x90' * (end - start - len(code)))


def validate_original(pe, data):
    assert pe.OPTIONAL_HEADER.ImageBase == BASE and pe.FILE_HEADER.Machine == 0x14C
    text = pe.sections[0]
    assert text.Name.rstrip(b'\0') == b'.text'
    assert text.VirtualAddress == 0x1000 and text.Misc_VirtualSize == 0x3DF38D
    assert text.SizeOfRawData == 0x3E0000 and text.Characteristics & 0x20000000
    expected_calls = ['esi', 'esi', 'edi', 'ebx']
    for region, expected_call in zip(REGIONS, expected_calls):
        start, end, _, _, selected = region
        instructions = list(DISASM.disasm(data[pe.get_offset_from_rva(start-BASE):pe.get_offset_from_rva(end-BASE)], start))
        assert instructions and instructions[-1].address + instructions[-1].size == end
        pairs = [(ins.mnemonic, ins.op_str) for ins in instructions]
        assert pairs[-1] == ('call', expected_call)
        assert ('push', '0x406') in pairs
        assert sum('word ptr [eax + 0x1488]' in op for _, op in pairs) == 1
        assert sum('word ptr [eax + 0x1480]' in op for _, op in pairs) == 1
        assert (('mov', 'ebp, dword ptr [0xa8b25c]') in pairs) == selected
    # Only the small reserved executable tail used by this patch is checked.
    offset = pe.get_offset_from_rva(CAVE-BASE)
    assert not any(data[offset:offset+0x300]), 'Executable tail is already occupied'
    for address, expected in [(0x61E59A, [('mov', 'ebp, dword ptr [esp + 0x160]'), ('mov', 'esi, ebp')]),
                              (0x6A8463, [('cmp', 'esi, 0x1f'), ('je', '0x6a8477')])]:
        offset = pe.get_offset_from_rva(address-BASE)
        pairs = [(i.mnemonic, i.op_str) for i in DISASM.disasm(data[offset:offset+20], address)]
        assert pairs[:len(expected)] == expected
    imports = {entry.name: entry.address for module in pe.DIRECTORY_ENTRY_IMPORT for entry in module.imports}
    assert imports[b'SendMessageA'] == 0x7E14A4
    assert imports[b'SendDlgItemMessageA'] == 0x7E1490


def verify(path):
    pe = pefile.PE(str(path))
    data = path.read_bytes()
    for region in REGIONS:
        start, end, register, dest, selected = region
        offset = pe.get_offset_from_rva(start-BASE)
        instructions = list(DISASM.disasm(data[offset:offset+end-start], start))
        calls = [i for i in instructions if i.mnemonic == 'call']
        assert len(calls) == 1 and int(calls[0].op_str, 16) == dest
        assert instructions[0].mnemonic == ('mov' if selected else 'push')
    for address, dialog in [(DIRECT, False), (DIALOG, True)]:
        offset = pe.get_offset_from_rva(address-BASE)
        instructions = list(DISASM.disasm(data[offset:offset+len(helper(dialog))], address))
        assert instructions[0].mnemonic == 'pushal' and instructions[-2].mnemonic == 'popal'
        assert instructions[-1].mnemonic == 'ret' and instructions[-1].op_str == '4'
        assert ('push', hex(RANGE_MARKER)) in [(i.mnemonic, i.op_str) for i in instructions]
    for address, destination in [(0x61E59A, RANGE_STUB), (0x6A8463, SORT_STUB)]:
        offset = pe.get_offset_from_rva(address-BASE)
        instruction = next(DISASM.disasm(data[offset:offset+5], address))
        assert instruction.mnemonic == 'jmp' and int(instruction.op_str, 16) == destination
    range_offset = pe.get_offset_from_rva(RANGE_STUB-BASE)
    pairs = [(i.mnemonic, i.op_str) for i in DISASM.disasm(data[range_offset:range_offset+len(range_stub())], RANGE_STUB)]
    assert ('mov', 'esi, dword ptr [ebp + 0x1480]') in pairs
    assert ('mov', 'ebp, dword ptr [ebp + 0x1488]') in pairs
    assert pe.sections[0].Misc_VirtualSize >= SORT_STUB + len(sort_stub()) - BASE - 0x1000
    return 'Custom slider DWORD range handler and SGSTART-last comparator redirects checked'


def build(source, destination):
    pe = pefile.PE(str(source))
    data = bytearray(source.read_bytes())
    validate_original(pe, data)
    for address, dialog in [(DIRECT, False), (DIALOG, True)]:
        offset = pe.get_offset_from_rva(address-BASE)
        stub = helper(dialog)
        data[offset:offset+len(stub)] = stub
    for region in REGIONS:
        start, end, *_ = region
        offset = pe.get_offset_from_rva(start-BASE)
        data[offset:offset+end-start] = hook(*region)
    for address, stub in [(RANGE_STUB, range_stub()), (SORT_STUB, sort_stub())]:
        offset = pe.get_offset_from_rva(address-BASE)
        data[offset:offset+len(stub)] = stub
    for start, end, target_address in [(0x61E59A, 0x61E5AE, RANGE_STUB), (0x6A8463, 0x6A8468, SORT_STUB)]:
        offset = pe.get_offset_from_rva(start-BASE)
        data[offset:offset+end-start] = redirect(start, end, target_address)
    new_size = SORT_STUB + len(sort_stub()) - BASE - pe.sections[0].VirtualAddress
    struct.pack_into('<I', data, pe.sections[0].get_field_absolute_offset('Misc_VirtualSize'), new_size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(verify(destination))


if __name__ == '__main__':
    game = Path(r'D:\Program\Game\RA2MD')
    state = json.loads((game / 'StartAttackMOD' / 'state-YR.json').read_text(encoding='utf-8-sig'))
    build(Path(state['backupDirectory']) / 'gamemd.exe', ROOT / '安装文件' / '尤里的复仇' / 'gamemd.exe')
