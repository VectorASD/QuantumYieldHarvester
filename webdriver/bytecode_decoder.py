from base64 import b64decode
from struct import unpack
from collections import deque
from pathlib import Path
import re
from io import StringIO


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
reg_names[201] = "result"
reg_names[229] = "Number"
reg_names[253] = "(void 0)"
reg_names[254] = "c1"  # constant 1
reg_names[255] = "c0"  # constant 0

class Reg:
    def __init__(self, idx):
        self.idx = idx
    def __repr__(self):
        idx = self.idx
        name = reg_names[idx]
        return f"reg{idx}" if name is None else name


def getByte():
    global pos
    byte = bytecode[pos]; pos += 1
    return byte

def getReg():
    return Reg(getByte())

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
    registers = tuple(map(Reg, bytecode[pos:pos+size]))
    pos += size
    return registers

def Caesar(shift, right, left):
    eval = (left + right).strip()
    assert eval[0] == '[' and eval[-1] == ']'
    return ''.join(chr(int(part) - shift) for part in eval[1:-1].split(',') if part.strip())

# print(Caesar(8, '5,]', '[10'))
# print(Caesar(7, '105,53,119,124,122,111,47,104,53,106,111,104,121,74,118,107,108,72,123,47,112,48,48,66,121,108,123,124,121,117,39,105,]', '[125,104,121,39,112,68,55,51,105,68,98,100,66,109,118,121,47,66,112,67,104,53,115,108,117,110,123,111,66,112,50,50,48,'))
# exit()


print_dispatch = [None] * 256
print_dispatch[  1] = lambda write, inst: write(f"  c | {inst[1]} = {repr(inst[2]) if isinstance(inst[2], str) else inst[2]}\n")
print_dispatch[  5] = lambda write, inst: write(f"  5 | {inst[1]} = [{', '.join(map(str, inst[2]))}]\n")
print_dispatch[ 10] = lambda write, inst: write(f" 10 | {inst[1]} = {inst[2]}[{inst[3]}]\n")
print_dispatch[ 11] = lambda write, inst: write(f" 11 | {inst[1]} = {inst[2]}.apply({inst[3]}, [{', '.join(map(str, inst[4]))}])\n")
def print_op_13(write, inst):
    _, goto, ret_reg, regs = inst
    write(f" 13 | reg_backups.push([regs[:], {ret_reg!r}])\n")
    for dst, src in regs:
        write(f"      {dst} = {src}\n")
    write(f"      call {goto}\n")
print_dispatch[ 13] = print_op_13
def print_op_14(write, inst):
    _, result_reg, regs = inst
    write(" 14 | _regs, ret_reg = reg_backups.pop()\n")
    write(f"      _regs[ret_reg] = {result_reg}\n")
    if regs:
        write(f"      mod_regs |= {set(regs)}\n")
    write("      _regs[mod_regs] = regs[mod_regs]\n")
    write("      if len(reg_backups) == 0: mod_regs.clear()\n")
    write("      regs = _regs\n")
print_dispatch[ 14] = print_op_14
print_dispatch[ 15] = lambda write, inst: write(f" 15 | {inst[1]} = {inst[2]}\n")
print_dispatch[ 16] = lambda write, inst: write( " 16 | HALT\n")
print_dispatch[ 17] = lambda write, inst: write(f" 17 | goto {inst[1]} if {inst[2]} else {inst[3]}\n")
print_dispatch[ 18] = lambda write, inst: write(f" 18 | goto {inst[1]}\n")
def print_op_20(write, inst):
    _, reg, goto, args = inst
    write(f" 20 | {reg} = function() {{\n")
    if args:
        write(f"  {', '.join(map(str, args))} = arguments\n")
    write(f"        reg_backups.push([regs[:], {Reg(201)!r})\n")
    write(f"        call {goto} while !{Reg(201)}\n")
    write(f"        return (delete {Reg(201)})\n")
    write("      }\n")
print_dispatch[ 20] = print_op_20
print_dispatch[ 21] = lambda write, inst: write(f" 21 | {inst[1]}[{inst[2]}] = {inst[3]}\n")
print_dispatch[ 50] = lambda write, inst: write(f" 5_ | {inst[1]} = {inst[2]} {inst[3]} {inst[4]}\n")
print_dispatch[100] = lambda write, inst: write(f"10_ | {inst[1]} = {inst[2]} {inst[3]} {inst[4]}\n")

def inst2str(inst):
    buffer = StringIO()
    print_dispatch[inst[0]](buffer.write, inst)
    return buffer.getvalue()
def bb2str(bb, insts):
    buffer = StringIO()
    write = buffer.write
    write(f"~~~ {bb}\n")
    for inst in insts:
        print_dispatch[inst[0]](write, inst)  
    return buffer.getvalue()
def print_cfg(FF):
    blocks, preds, succs, calls = FF
    for bb, insts in blocks.items():
        bb_name = (str(bb), f"  // preds: {preds[bb]}" if preds[bb] else '', f"  // calls: {calls[bb]}" if calls[bb] else '')
        print(bb2str(''.join(bb_name), insts))


EOB = True  # end of block

def op_1():
    reg = getReg()
    str = loadString()
    return 0, (1, reg, str)  # {reg} = {str!r}
def op_2():
    reg = getReg()
    num = getByte()
    return 0, (1, reg, num)  # {reg} = {num}
def op_3():
    reg = getReg()
    num = loadFloat()
    return 0, (1, reg, num)  # {reg} = {num}
def op_4():
    reg = getReg()
    num = loadLongNum()
    return 0, (1, reg, num)  # {reg} = {num}
def op_5():
    reg = getReg()
    arr = loadRegistersArray()
    return 0, (5, reg, arr)  # {reg} = [{', '.join(map(str, arr))}]

def op_10():
    set_reg = getReg()
    arr_reg = getReg()
    idx_reg = getReg()
    return 0, (10, set_reg, arr_reg, idx_reg)  # {set_reg} = {arr_reg}[{idx_reg}]]

def op_11():
    set_reg = getReg()
    func_reg = getReg()
    this_reg = getReg()
    arr = loadRegistersArray()
    # {set_reg} = {func_reg}.apply({this_reg}, [{', '.join(map(str, arr))}])
    return 0, (11, set_reg, func_reg, this_reg, arr)

# 12 - eval

def op_13():
    goto = loadLongNum()
    ret_reg = getByte()
    regs = loadRegistersArray()
    assert len(regs) % 2 == 0
    regs = [(regs[i], regs[i+1]) for i in range(0, len(regs), 2)]
    queue.append(goto)
    return 0, [13, goto, ret_reg, regs]  # call

def op_14():
    result_reg = getReg()
    regs = loadRegistersArray()
    return EOB, (14, result_reg, regs)  # return

def op_15():
    dst = getReg()
    src = getReg()
    return 0, (15, dst, src)  # {dst} = {src}

def op_16():
    return EOB, (16,)  # HALT
def op_17():
    reg = getReg()
    goto = loadLongNum()
    queue.append(pos)
    queue.append(goto)
    return EOB, [17, goto, reg, pos]  # goto {goto} if {reg} else {pos}
def op_18():
    goto = loadLongNum()
    queue.append(goto)
    return EOB, [18, goto]  # goto {goto}
def op_19():
    reg = getReg()
    goto = loadLongNum()
    queue.append(pos)
    queue.append(goto)
    return EOB, [17, pos, reg, goto]  # goto {pos} if {reg} else {goto}

def op_20():
    reg = getReg()
    goto = loadLongNum()
    args = loadRegistersArray()
    queue.append(goto)
    return 0, [20, reg, goto, args]

def op_21():
    arr_reg = getReg()
    idx_reg = getReg()
    val_reg = getReg()
    return 0, (21, arr_reg, idx_reg, val_reg)  # {arr_reg}[{idx_reg}] = {val_reg}

# 22 - catch
# 23 - throw

def op_50():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, "==", R)
def op_51():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, "!=", R)
def op_52():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, "===", R)
def op_53():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, "!==", R)
def op_54():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, '<', R)
def op_55():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, '>', R)
def op_56():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, "<=", R)
def op_57():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (50, reg, L, ">=", R)

def op_100():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (100, reg, L, '+', R)
def op_101():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (100, reg, L, '*', R)
def op_102():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (100, reg, L, '-', R)
def op_103():
    reg = getReg()
    L = getReg()
    R = getReg()
    return 0, (100, reg, L, '/', R)


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
def stage1(start_pos=0):
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
      # print("\nstart_pos:", pos)
        while pos < len(bytecode):
            kind = getByte()
            if ops[kind] is None:
                print("kind:", kind)
                exit()
            eob, _ = ops[kind]()
            if eob:
                break
      # print("end_pos:", pos)
        for i in range(start_pos, pos):
            visited[i] = True

    unvisited = [i for i in range(len(bytecode)) if not visited[i]]
    print("unvisited bytes:", unvisited)
    print("subprograms:", len(subprograms))
    print("gotos:", len(gotos))
    ungotos = set(goto for goto in gotos if goto not in subprograms)
    print("ungotos:", len(ungotos))
    return gotos


class Block:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return f"BB{self.name}"

def make_cfg(blocks):
    succs = {bb: set() for bb in blocks}
    calls = {bb: set() for bb in blocks}
    for bb, insts in blocks.items():
        for inst in insts:
            kind = inst[0]
            if kind == 13:
                calls[inst[1]].add(bb)
            elif kind == 20:
                calls[inst[2]].add(bb)
        term_inst = insts[-1]
        kind = term_inst[0]
        if kind in (17, 18):
            succs[bb].add(term_inst[1])
            if kind == 17:
                succs[bb].add(term_inst[3])
        elif kind == 20:
            succs[bb].add(term_inst[2])

    preds = {bb: [] for bb in blocks}
    for bb, bb_succ in succs.items():
        for succ in bb_succ:
            preds[succ].append(bb)
    return blocks, preds, succs, calls


def stage2(gotos):
    global pos
    _range = range(len(bytecode))
    for goto in gotos:
        assert goto in _range

    gotos.add(len(bytecode))
    gotos = sorted(gotos)
    goto2bb = {goto: Block(i) for i, goto in enumerate(gotos)}
    blocks = {}

    for i in range(len(gotos) - 1):
        start_pos = pos = gotos[i]
        end_pos = gotos[i+1]
        insts = []
        add = insts.append
        while pos < end_pos:
            kind = getByte()
            eob, inst = ops[kind]()
            if pos < end_pos:
                assert not eob
            add(inst)
            if kind == 13:
                inst[1] = goto2bb[inst[1]]
            elif kind == 20:
                inst[2] = goto2bb[inst[2]]
        if not eob:
            add([18, pos])  # goto {pos}

        term_inst = insts[-1]
        kind = term_inst[0]
        if kind in (17, 18):
            term_inst[1] = goto2bb[term_inst[1]]
            if kind == 17:
                term_inst[3] = goto2bb[term_inst[3]]
        elif kind == 20:
            term_inst[2] = goto2bb[term_inst[2]]
        blocks[goto2bb[start_pos]] = insts

    FF = make_cfg(blocks)
    print_cfg(FF)


def main():
    gotos = stage1()
    stage2(gotos)


if __name__ == "__main__":
    main()
