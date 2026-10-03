from pathlib import Path
import struct
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / '工具依赖'))
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from patch_money_slider import Code, RANGE_MARKER

BASE = 0x400000
CAVE = 0x784B50
DIRECT = CAVE
DIALOG = CAVE + 0x80
RANGE_STUB = CAVE + 0x100
SORT_STUB = CAVE + 0x200
RULES = 0x821B68
SELECTED = 0xA255CC
REGIONS = [(0x593507, 0x59352E, 'edi', DIRECT, False),
           (0x596992, 0x5969BF, 'edi', DIRECT, True),
           (0x5BE083, 0x5BE0AF, 'esi', DIALOG, False),
           (0x679AAA, 0x679AD1, 'esi', DIRECT, False)]
DISASM = Cs(CS_ARCH_X86, CS_MODE_32)


def helper(dialog):
    code = bytearray(b'\x60\x8b\x7c\x24\x24\x8b\x1d' + struct.pack('<I', RULES))
    code += b'\x53\x68' + struct.pack('<I', RANGE_MARKER)
    code += b'\x68' + struct.pack('<I', 0x406)
    if dialog:
        code += b'\x68' + struct.pack('<I', 0x402)
    code += b'\x57\xff\x15' + struct.pack('<I', 0x785480 if dialog else 0x78549C)
    return bytes(code + b'\x61\xc2\x04\x00')


def hook(start, end, register, target, selected):
    code = bytearray(b'\x8b\x2d' + struct.pack('<I', SELECTED) if selected else b'')
    code += b'\x57' if register == 'edi' else b'\x56'
    address = start + len(code)
    code += b'\xe8' + struct.pack('<i', target - address - 5)
    return bytes(code + b'\x90' * (end - start - len(code)))


def range_stub():
    code = Code(RANGE_STUB)
    code.emit(b'\x8b\xac\x24\x60\x01\x00\x00')
    code.emit(b'\x81\xbc\x24\x5c\x01\x00\x00' + struct.pack('<I', RANGE_MARKER))
    code.jump('packed', 0x85)
    code.emit(b'\x8b\xb5\xe8\x10\x00\x00\x8b\xad\xf0\x10\x00\x00')
    code.jump('continue')
    code.label('packed')
    code.emit(b'\x8b\xf5\x81\xe6\xff\xff\x00\x00\xc1\xed\x10')
    code.label('continue')
    code.emit(b'\x2b\xee')
    code.jump(0x5F3BA6)
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
    code.emit(b'\x61\x83\xfe\x1f')
    code.jump(0x6740C7, 0x84)
    code.jump(0x6740B8)
    code.label('last')
    code.emit(b'\x61')
    code.jump(0x6742F0)
    code.label('first')
    code.emit(b'\x61')
    code.jump(0x6742E2)
    return code.finish()


def redirect(start, end, destination):
    return b'\xe9' + struct.pack('<i', destination-start-5) + b'\x90' * (end-start-5)


def validate_original(pe, data):
    assert pe.OPTIONAL_HEADER.ImageBase == BASE and pe.FILE_HEADER.Machine == 0x14C
    text = pe.sections[0]
    assert text.Name.rstrip(b'\0') == b'.text'
    assert text.VirtualAddress == 0x1000 and text.Misc_VirtualSize == 0x383B4D
    assert text.SizeOfRawData == 0x384000 and text.Characteristics & 0x20000000
    assert pe.OPTIONAL_HEADER.SizeOfImage == 0x729000
    for region, expected_call in zip(REGIONS, ['esi', 'esi', 'edi', 'edi']):
        start, end, _, _, selected = region
        off = pe.get_offset_from_rva(start-BASE)
        pairs = [(i.mnemonic, i.op_str) for i in DISASM.disasm(data[off:off+end-start], start)]
        assert pairs[-1] == ('call', expected_call)
        assert ('push', '0x406') in pairs
        assert sum('word ptr [eax + 0x10f0]' in op for _, op in pairs) == 1
        assert sum('word ptr [eax + 0x10e8]' in op for _, op in pairs) == 1
        assert (('mov', 'ebp, dword ptr [0xa255cc]') in pairs) == selected
    for start, expected in [(0x5F3B92, [('mov', 'ebp, dword ptr [esp + 0x160]'), ('mov', 'esi, ebp')]),
                            (0x6740B3, [('cmp', 'esi, 0x1f'), ('je', '0x6740c7')])]:
        off = pe.get_offset_from_rva(start-BASE)
        assert [(i.mnemonic, i.op_str) for i in DISASM.disasm(data[off:off+20], start)][:len(expected)] == expected
    off = pe.get_offset_from_rva(CAVE-BASE)
    assert not any(data[off:off+0x300]), 'Executable cave is occupied'
    imports = {entry.name: entry.address for module in pe.DIRECTORY_ENTRY_IMPORT for entry in module.imports}
    assert imports[b'SendMessageA'] == 0x78549C
    assert imports[b'SendDlgItemMessageA'] == 0x785480


def verify(path):
    pe = pefile.PE(str(path))
    data = path.read_bytes()
    for start, end, register, target, selected in REGIONS:
        off = pe.get_offset_from_rva(start-BASE)
        instructions = list(DISASM.disasm(data[off:off+end-start], start))
        calls = [i for i in instructions if i.mnemonic == 'call']
        assert len(calls) == 1 and int(calls[0].op_str, 16) == target
        assert instructions[0].mnemonic == ('mov' if selected else 'push')
    for address, dialog in [(DIRECT, False), (DIALOG, True)]:
        off = pe.get_offset_from_rva(address-BASE)
        instructions = list(DISASM.disasm(data[off:off+len(helper(dialog))], address))
        assert instructions[0].mnemonic == 'pushal' and instructions[-2].mnemonic == 'popal'
        assert instructions[-1].mnemonic == 'ret' and instructions[-1].op_str == '4'
        assert ('push', hex(RANGE_MARKER)) in [(i.mnemonic, i.op_str) for i in instructions]
    for address, destination in [(0x5F3B92, RANGE_STUB), (0x6740B3, SORT_STUB)]:
        off = pe.get_offset_from_rva(address-BASE)
        instruction = next(DISASM.disasm(data[off:off+5], address))
        assert instruction.mnemonic == 'jmp' and int(instruction.op_str, 16) == destination
    off = pe.get_offset_from_rva(RANGE_STUB-BASE)
    pairs = [(i.mnemonic, i.op_str) for i in DISASM.disasm(data[off:off+len(range_stub())], RANGE_STUB)]
    assert ('mov', 'esi, dword ptr [ebp + 0x10e8]') in pairs
    assert ('mov', 'ebp, dword ptr [ebp + 0x10f0]') in pairs
    assert pe.sections[0].Misc_VirtualSize >= SORT_STUB+len(sort_stub())-BASE-0x1000
    return 'RA2 1.08 custom slider and SGSTART-last comparator redirects checked'


def build(source, destination):
    pe = pefile.PE(str(source))
    data = bytearray(source.read_bytes())
    validate_original(pe, data)
    for address, stub in [(DIRECT, helper(False)), (DIALOG, helper(True)),
                          (RANGE_STUB, range_stub()), (SORT_STUB, sort_stub())]:
        off = pe.get_offset_from_rva(address-BASE)
        data[off:off+len(stub)] = stub
    for region in REGIONS:
        start, end, *_ = region
        off = pe.get_offset_from_rva(start-BASE)
        data[off:off+end-start] = hook(*region)
    for start, end, target in [(0x5F3B92, 0x5F3BA6, RANGE_STUB), (0x6740B3, 0x6740B8, SORT_STUB)]:
        off = pe.get_offset_from_rva(start-BASE)
        data[off:off+end-start] = redirect(start, end, target)
    size = SORT_STUB+len(sort_stub())-BASE-pe.sections[0].VirtualAddress
    struct.pack_into('<I', data, pe.sections[0].get_field_absolute_offset('Misc_VirtualSize'), size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(verify(destination))
