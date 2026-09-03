from base64 import b64decode
from struct import unpack
from collections import deque
from pathlib import Path
import re


bytecode_path = Path(__file__).parent / "polygon" / "challenge2.js"
match = re.search(rb'a\.init\(\s*"([A-Za-z0-9+/=]+)"', bytecode_path.read_bytes())
if not match:
    raise RuntimeError("Bytecode string not found")
bytecode = b64decode(match.group(1))
# print(len(bytecode))  # 28728

reg_names = [None] * 256
reg_names[  1] = "Function"
reg_names[ 28] = "String"
reg_names[ 29] = "window"
reg_names[ 35] = "Math"
reg_names[ 41] = "Promise"
reg_names[ 48] = "Boolean"
reg_names[ 51] = "Float32Array"
reg_names[ 59] = "null"
reg_names[ 63] = "undefined"
reg_names[ 72] = "performance"
reg_names[ 82] = "RegExp"
reg_names[ 91] = "Array"
reg_names[125] = "document"
reg_names[176] = "Object"
reg_names[200] = "pos"  # instruction counter
reg_names[229] = "Number"
reg_names[253] = "(void 0)"
reg_names[254] = "c1"  # constant 1
reg_names[255] = "c0"  # constant 0
def reg2name(idx):
    name = reg_names[idx]
    return f"regs[{idx}]" if name is None else name


def getByte():
    global pos
    byte = bytecode[pos]; pos += 1
    return byte

def loadLongNum():
    global pos
    num = unpack(">I", bytecode[pos:pos+4])[0]
    pos += 4
    return num

def loadString():
    global pos
    size = unpack(">H", bytecode[pos:pos+2])[0]; pos += 2
    str = ''.join(map(chr, bytecode[pos:pos+size]))
    pos += size
    return str

def loadFloat():
    global pos
    num = unpack(">d", bytecode[pos:pos+8])[0]
    pos += 8
    return num

def loadRegistersArray():
    global pos
    size = bytecode[pos]; pos += 1
    registers = tuple(bytecode[pos:pos+size])
    pos += size
    return registers

def loadArrayFromRegister():
    arr = ", ".join(reg2name(reg) for reg in loadRegistersArray())
    return f"[{arr}]"

def Caesar(shift, right, left):
    eval = (left + right).strip()
    assert eval[0] == '[' and eval[-1] == ']'
    return ''.join(chr(int(part) - shift) for part in eval[1:-1].split(',') if part.strip())

# print(Caesar(8, '5,]', '[10'))
# print(Caesar(7, '105,53,119,124,122,111,47,104,53,106,111,104,121,74,118,107,108,72,123,47,112,48,48,66,121,108,123,124,121,117,39,105,]', '[125,104,121,39,112,68,55,51,105,68,98,100,66,109,118,121,47,66,112,67,104,53,115,108,117,110,123,111,66,112,50,50,48,'))
# exit()


def op_1():
    reg = getByte()
    str = loadString()
    print(f"  1 | {reg2name(reg)} = {str!r}")
def op_2():
    reg = getByte()
    num = getByte()
    print(f"  2 | {reg2name(reg)} = {num}")
def op_3():
    reg = getByte()
    num = loadFloat()
    print(f"  3 | {reg2name(reg)} = {num}")
def op_4():
    reg = getByte()
    num = loadLongNum()
    print(f"  4 | {reg2name(reg)} = {num}")
def op_5():
    reg = getByte()
    arr = loadArrayFromRegister()
    print(f"  5 | {reg2name(reg)} = {arr}")

def op_10():
    set_reg = getByte()
    arr_reg = getByte()
    idx_reg = getByte()
    print(f" 10 | {reg2name(set_reg)} = {reg2name(arr_reg)}[{reg2name(idx_reg)}]]")

def op_11():
    set_reg = getByte()
    func_reg = getByte()
    this_reg = getByte()
    arr = loadArrayFromRegister()
    print(f" 11 | {reg2name(set_reg)} = {reg2name(func_reg)}.apply({reg2name(this_reg)}, {arr})")

# 12 - eval

def op_13():
    goto = loadLongNum()
    code = getByte()
    regs = loadRegistersArray()
    print(f" 13 | reg_backups.push([regs[:], {code}])")
    assert len(regs) % 2 == 0
    for i in range(0, len(regs), 2):
        print(f"      {reg2name(regs[i])} = {reg2name(regs[i+1])}")
    print(f"      goto {goto}")
    queue.append(goto)

def op_14():
    result_reg = getByte()
    regs = loadRegistersArray()
    print(" 14 | _regs, ret_reg = reg_backups.pop()")
    print(f"      _regs[ret_reg] = {reg2name(result_reg)}")
    print(f"      mod_regs |= {set(regs)}")
    print("      _regs[mod_regs] = regs[mod_regs]")
    print("      if len(reg_backups) == 0: mod_regs.clear()")
    print("      regs = _regs")
    return True  # eob

def op_15():
    dst = getByte()
    src = getByte()
    print(f" 15 | {reg2name(dst)} = {reg2name(src)}")

def op_16():
    print(" 16 | HALT")
    return True  # eob
def op_17():
    reg = getByte()
    goto = loadLongNum()
    print(f" 17 | goto {goto} if {reg2name(reg)} else {pos}")
    queue.append(pos)
    queue.append(goto)
    return True  # eob
def op_18():
    goto = loadLongNum()
    print(f" 18 | goto {goto}")
    queue.append(goto)
    return True  # eob
def op_19():
    reg = getByte()
    goto = loadLongNum()
    print(f" 19 | goto {pos} if {reg2name(reg)} else {goto}")
    queue.append(pos)
    queue.append(goto)
    return True  # eob

def op_20():
    reg = getByte()
    goto = loadLongNum()
    args = loadArrayFromRegister()
    print(f" 20 | {reg2name(reg)} = function() {{")
    if args:
        print(f"  {args} = arguments")
    print(f"        reg_backups.push([regs[:], 201])")
    print(f"        call {goto} while !regs[201]")
    print(f"        return (delete regs[201])")
    print("      }")
    queue.append(goto)

def op_21():
    arr_reg = getByte()
    idx_reg = getByte()
    val_reg = getByte()
    print(f" 21 | {reg2name(arr_reg)}[{reg2name(idx_reg)}] = {reg2name(val_reg)}")
# 22 - catch
# 23 - throw

def op_50():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 50 | {reg2name(reg)} = {reg2name(L)} == {reg2name(R)}")
def op_51():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 51 | {reg2name(reg)} = {reg2name(L)} != {reg2name(R)}")
def op_52():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 52 | {reg2name(reg)} = {reg2name(L)} === {reg2name(R)}")
def op_53():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 53 | {reg2name(reg)} = {reg2name(L)} !== {reg2name(R)}")
def op_54():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 54 | {reg2name(reg)} = {reg2name(L)} < {reg2name(R)}")
def op_55():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 55 | {reg2name(reg)} = {reg2name(L)} > {reg2name(R)}")
def op_56():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 56 | {reg2name(reg)} = {reg2name(L)} <= {reg2name(R)}")
def op_57():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f" 57 | {reg2name(reg)} = {reg2name(L)} >= {reg2name(R)}")

def op_100():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f"100 | {reg2name(reg)} = {reg2name(L)} + {reg2name(R)}")
def op_101():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f"101 | {reg2name(reg)} = {reg2name(L)} * {reg2name(R)}")
def op_102():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f"102 | {reg2name(reg)} = {reg2name(L)} - {reg2name(R)}")
def op_103():
    reg = getByte()
    L = getByte()
    R = getByte()
    print(f"103 | {reg2name(reg)} = {reg2name(L)} / {reg2name(R)}")


ops = [None] * 256
ops[1:6] = op_1, op_2, op_3, op_4, op_5  # const
ops[ 10] = op_10  # getitem
ops[ 11] = op_11  # func.apply
ops[ 13] = op_13  # call
ops[ 14] = op_14  # return
ops[ 15] = op_15  # move
ops[16:20] = op_16, op_17, op_18, op_19  # CFG
ops[ 20] = op_20  # call with return check
ops[ 21] = op_21  # setitem
ops[50:58] = op_50, op_51, op_52, op_53, op_54, op_55, op_56, op_57  # comparison
ops[100:104] = op_100, op_101, op_102, op_103  # arithmetic

queue = deque()
def main(start_pos=0):
    global pos

    visited = [False] * len(bytecode)
    subprograms = set()  # нормальные начала подпрограмм
    gotos = set()  # любые переходы, даже в середину подпрограммы

    queue.append(start_pos)
    while queue:
        pos = start_pos = queue.popleft()
        gotos.add(start_pos)
        if visited[pos]:
            continue
        subprograms.add(start_pos)
        print("\nstart_pos:", pos)
        while pos < len(bytecode):
            kind = getByte()
            if ops[kind] is None:
                print("kind:", kind)
                exit()
            if ops[kind]():
                break
        print("end_pos:", pos)
        for i in range(start_pos, pos):
            visited[i] = True

    unvisited = [i for i in range(len(bytecode)) if not visited[i]]
    print("unvisited bytes:", unvisited)
    print("subprograms:", len(subprograms))
    print("gotos:", len(gotos))
    ungotos = set(goto for goto in gotos if goto not in subprograms)
    print("ungotos:", len(ungotos))


if __name__ == "__main__":
    main()
