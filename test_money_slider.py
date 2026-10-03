from pathlib import Path
import struct
import sys
from patch_money_slider import ROOT, REGIONS, BASE, SELECTED, RANGE_MARKER
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

REGISTERS = [UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
             UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP]
image = ROOT / '_build' / '安装文件' / '尤里的复仇' / 'gamemd.exe'
pe = pefile.PE(str(image))


def test(region, maximum):
    start, end, register, _, selected = region
    emulator = Uc(UC_ARCH_X86, UC_MODE_32)
    emulator.mem_map(BASE, (max(pe.OPTIONAL_HEADER.SizeOfImage, 0x710000) + 0xFFF) & ~0xFFF)
    emulator.mem_write(BASE, pe.get_memory_mapped_image())
    emulator.mem_map(0x2000000, 0x10000)
    stack = 0x2008000
    emulator.reg_write(UC_X86_REG_ESP, stack)
    originals = {reg: 0x100 + index for index, reg in enumerate(REGISTERS)}
    for reg, value in originals.items():
        emulator.reg_write(reg, value)
    hwnd = originals[UC_X86_REG_EDI if register == 'edi' else UC_X86_REG_ESI]
    rules = 0xAE0000
    emulator.mem_write(0x8871E0, struct.pack('<I', rules))
    emulator.mem_write(rules + 0x1480, struct.pack('<4I', 5000, 10000, maximum, 100))
    emulator.mem_write(SELECTED, struct.pack('<I', 41200))
    api = {0xAF0000: (4, 0x7E14A4), 0xAF0010: (5, 0x7E1490)}
    for address, (_, iat) in api.items():
        emulator.mem_write(iat, struct.pack('<I', address))
        emulator.mem_write(address, b'\xc3')
    calls = []

    def dispatch(uc, address, size, userdata):
        if address not in api:
            return
        count, _ = api[address]
        esp = uc.reg_read(UC_X86_REG_ESP)
        values = struct.unpack('<' + 'I' * (count+1), uc.mem_read(esp, (count+1)*4))
        calls.append(values[1:])
        # Simulate the documented stdcall boundary including caller-saved clobbers.
        for reg in [UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX]:
            uc.reg_write(reg, 0xBAD)
        uc.reg_write(UC_X86_REG_ESP, esp+(count+1)*4)
        uc.reg_write(UC_X86_REG_EIP, values[0])

    emulator.hook_add(UC_HOOK_CODE, dispatch)
    emulator.emu_start(start, end, count=200)
    expected = [(hwnd, 0x406, RANGE_MARKER, rules)]
    if start == 0x5E3153:
        expected = [(hwnd, 0x402, *values[1:]) for values in expected]
    assert calls == expected, (region, calls, expected)
    assert emulator.reg_read(UC_X86_REG_ESP) == stack
    for reg, value in originals.items():
        expected_reg = 41200 if selected and reg == UC_X86_REG_EBP else value
        assert emulator.reg_read(reg) == expected_reg, (reg, region)


for region in REGIONS:
    for maximum in [10000, 500000]:
        test(region, maximum)
print('Eight initialization cases passed: custom range message, stdcall stack and register restoration')


def machine():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(BASE, (max(pe.OPTIONAL_HEADER.SizeOfImage, 0x710000) + 0xFFF) & ~0xFFF)
    uc.mem_write(BASE, pe.get_memory_mapped_image())
    uc.mem_map(0x2000000, 0x10000)
    return uc


def actual_slider(maximum, packed=False):
    uc = machine()
    obj, stack, rules = 0xAE5000, 0x2008000, 0xAE0000
    uc.mem_write(rules+0x1480, struct.pack('<4I', 5000, 10000, maximum, 100))
    uc.mem_write(obj+0xF0, struct.pack('<3I', 100, 0, 0))
    minimum, maximum = (1, 20) if packed else (5000, maximum)

    def send(message, wparam, lparam, getter=False):
        span, position, low = struct.unpack('<3I', uc.mem_read(obj+0xF0, 12))
        uc.reg_write(UC_X86_REG_ESP, stack)
        uc.reg_write(UC_X86_REG_EDI, obj)
        uc.reg_write(UC_X86_REG_EDX, message)
        uc.reg_write(UC_X86_REG_EAX, 140)
        uc.reg_write(UC_X86_REG_EBP, span)
        uc.reg_write(UC_X86_REG_EBX, position)
        uc.reg_write(UC_X86_REG_ESI, low)
        for offset, value in [(0x10, 140), (0x1C, 1 if packed else 100),
                              (0x150, 0xAF0020), (0x158, message), (0x15C, wparam), (0x160, lparam)]:
            uc.mem_write(stack+offset, struct.pack('<I', value))
        uc.emu_start(0x61E459, 0xAF0020 if getter else 0x61E670, count=500)
        return uc.reg_read(UC_X86_REG_EAX)

    send(0x406, 1 if packed else RANGE_MARKER, (maximum<<16)|minimum if packed else rules)
    assert struct.unpack('<I', uc.mem_read(obj+0xF0, 4))[0] == maximum-minimum
    assert struct.unpack('<I', uc.mem_read(obj+0xF8, 4))[0] == minimum
    for value in [minimum, (minimum+maximum)//2//(1 if packed else 100)*(1 if packed else 100), maximum]:
        send(0x405, 1, value)
        assert send(0x400, 0, 0, getter=True) == value, value


actual_slider(10000)
actual_slider(500000)
actual_slider(20, packed=True)
print('Actual custom slider range, position and getter machine code passed for 5000..500000, 5000..10000 and normal packed 1..20')


def comparator(left, right):
    uc = machine()
    stack, left_ptr, right_ptr = 0x2008000, 0xAE0000, 0xAE2000
    pointers = {0: 0, 1: left_ptr, 2: right_ptr}
    for ptr, name in [(left_ptr, left), (right_ptr, right)]:
        uc.mem_write(ptr+0x24, (name or 'NORMAL').encode('ascii')+b'\0')
    uc.reg_write(UC_X86_REG_ESP, stack)
    args = (0xAF0020, 3, 1, 3, 2)
    uc.mem_write(stack, struct.pack('<5I', *args))
    result = {}

    def dispatch(uc, address, size, userdata):
        if address == 0x48DCD0:
            ptr = pointers[uc.reg_read(UC_X86_REG_EDX)]
            uc.reg_write(UC_X86_REG_EAX, ptr)
            esp = uc.reg_read(UC_X86_REG_ESP)
            target = struct.unpack('<I', uc.mem_read(esp, 4))[0]
            uc.reg_write(UC_X86_REG_ESP, esp+4)
            uc.reg_write(UC_X86_REG_EIP, target)
        elif address in [0x6A8468, 0x6A8477]:
            result['native'] = True
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, dispatch)
    uc.emu_start(0x6A8420, 0xAF0020, count=300)
    if result:
        return 'native'
    assert uc.reg_read(UC_X86_REG_ESP) == stack+20
    return bool(uc.reg_read(UC_X86_REG_EAX)&0xFF)


assert comparator('SGSTART', 'GAPOWR') is False
assert comparator('GAPOWR', 'SGSTART') is True
assert comparator('SGSTART', 'SGSTART') is False
assert comparator('GAPOWR', 'GATECH') == 'native'
print('Native comparator execution passed: SGSTART sorts after all other items and normal comparisons continue unchanged')
