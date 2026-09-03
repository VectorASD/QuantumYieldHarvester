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

class Expression: pass

class Reg(Expression):
    def __init__(self, id):
        self.id = id
    def __repr__(self):
        id = self.id
        name = reg_names[id]
        return f"reg{id}" if name is None else name
    def __eq__(self, value):
        return isinstance(value, Reg) and self.id == value
    def __hash__(self):
        return hash(self.id)
    def uses(self, add):
        add(self)

class RegIndex(Expression):
    def __init__(self, reg, index):
        self.reg = reg
        self.index = index
    def __repr__(self):
        index = self.index
        if isinstance(index, str) and index.isidentifier():
            return f"{self.reg}.{index}"
        return f"{self.reg}[{index!r}]"
    def uses(self, add):
        reg, index = self.reg, self.index
        if isinstance(reg, Expression):
            reg.uses(add)
        if isinstance(index, Expression):
            index.uses(add)

class RegArray(Expression):
    def __init__(self, items):
        self.items = tuple(items)
    def __repr__(self):
        arr = ', '.join(map(repr, self.items))
        return f"[{arr}]"
    def __bool__(self):
        return bool(self.items)
    def __len__(self):
        return len(self.items)
    def __getitem__(self, idx):
        return self.items[idx]
    def uses(self, add):
        for item in self.items:
            if isinstance(item, Expression):
                item.uses(add)
    def expandleft(self, item):
        self.items = (item, *self.items)
        return self

class RegCall(Expression):
    def __init__(self, func, this, args):
        self.func = func
        self.this = this
        self.args = args  # RegArray

    def __repr__(self):
        return f"{self.func}.apply({self.this}, {self.args})"

    def uses(self, add):
        if isinstance(self.func, Expression):
            self.func.uses(add)
        if isinstance(self.this, Expression):
            self.this.uses(add)
        self.args.uses(add)

class RegSetItem(Expression):
    def __init__(self, obj, index, value):
        self.obj = obj
        self.index = index
        self.value = value
    def __repr__(self):
        return f"{self.obj}[{self.index}] = {self.value}"
    def uses(self, add):
        for part in (self.obj, self.index, self.value):
            if isinstance(part, Expression):
                part.uses(add)

class BinOp(Expression):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right
    def __repr__(self):
        return f"{self.left} {self.op} {self.right}"
    def uses(self, add):
        if isinstance(self.left, Expression):
            self.left.uses(add)
        if isinstance(self.right, Expression):
            self.right.uses(add)


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
    array = RegArray(map(Reg, bytecode[pos:pos+size]))
    pos += size
    return array

def Caesar(shift, right, left):
    eval = (left + right).strip()
    assert eval[0] == '[' and eval[-1] == ']'
    return ''.join(chr(int(part) - shift) for part in eval[1:-1].split(',') if part.strip())

# print(Caesar(8, '5,]', '[10'))
# print(Caesar(7, '105,53,119,124,122,111,47,104,53,106,111,104,121,74,118,107,108,72,123,47,112,48,48,66,121,108,123,124,121,117,39,105,]', '[125,104,121,39,112,68,55,51,105,68,98,100,66,109,118,121,47,66,112,67,104,53,115,108,117,110,123,111,66,112,50,50,48,'))
# exit()


HAS_LHS = [False] * 256
for kind in (1, 5, 10, 11, 15, 30, 31, 50, 100):
    HAS_LHS[kind] = True
HAS_USES = {
    5: 2, 10: 2, 11: 2, 14: 1,
    15: 2, 17: 2, 21: 1,
    30: 2, 50: 2, 100: 2,
}

HAS_LHS = tuple(HAS_LHS)
HAS_USES = tuple(HAS_USES.get(i) for i in range(256))

print_dispatch = [None] * 256
print_dispatch[  1] = lambda write, inst: write(f"  c | {inst[1]} = {repr(inst[2]) if isinstance(inst[2], str) else inst[2]}\n")
print_dispatch[  5] = lambda write, inst: write(f"  5 | {inst[1]} = {inst[2]}\n")
print_dispatch[ 10] = lambda write, inst: write(f" 10 | {inst[1]} = {inst[2]}\n")
print_dispatch[ 11] = lambda write, inst: write(f" 11 | {inst[1]} = {inst[2]}\n")
print_dispatch[ 13] = lambda write, inst: write(f" 13 | reg_backups.push([regs[:], ...])\n")
def print_op_14(write, inst):
    _, regs = inst
    result_reg = regs.items[0]
    write(" 14 | _regs, ret_reg = reg_backups.pop()\n")
    write(f"      _regs[ret_reg] = {result_reg}\n")
    if regs:
        write(f"      mod_regs |= {set(regs.items[1:])}\n")
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
        write(f"  {str(args)[1:-1]} = arguments\n")
    write(f"        reg_backups.push([regs[:], {Reg(201)!r})\n")
    write(f"        call {goto} while !{Reg(201)}\n")
    write(f"        return (delete {Reg(201)})\n")
    write("      }\n")
print_dispatch[ 20] = print_op_20
print_dispatch[ 21] = lambda write, inst: write(f" 21 | {inst[1]}\n")
print_dispatch[ 30] = lambda write, inst: write(f"      {inst[1]} = {inst[2]}\n")  # from op_13
print_dispatch[ 31] = lambda write, inst: write(f"      {inst[1]} = call {inst[2]}\n")  # from op_13
print_dispatch[ 50] = lambda write, inst: write(f" 5_ | {inst[1]} = {inst[2]}\n")
print_dispatch[100] = lambda write, inst: write(f"10_ | {inst[1]} = {inst[2]}\n")

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

def op_1(add):
    reg = getReg()
    str = loadString()
    add((1, reg, str))  # {reg} = {str!r}
    return 0
def op_2(add):
    reg = getReg()
    num = getByte()
    add((1, reg, num))  # {reg} = {num}
    return 0
def op_3(add):
    reg = getReg()
    num = loadFloat()
    add((1, reg, num))  # {reg} = {num}
    return 0
def op_4(add):
    reg = getReg()
    num = loadLongNum()
    add((1, reg, num))  # {reg} = {num}
    return 0
def op_5(add):
    reg = getReg()
    arr = loadRegistersArray()
    add((5, reg, arr))  # {reg} = {arr}
    return 0

def op_10(add):
    set_reg = getReg()
    arr_reg = getReg()
    idx_reg = getReg()
    add((10, set_reg, RegIndex(arr_reg, idx_reg)))  # {set_reg} = {arr_reg}[{idx_reg}]]
    return 0

def op_11(add):
    set_reg = getReg()
    func_reg = getReg()
    this_reg = getReg()
    args = loadRegistersArray()
    # {set_reg} = {func_reg}.apply({this_reg}, {args})
    add((11, set_reg, RegCall(func_reg, this_reg, args)))
    return 0

# 12 - eval

def op_13(add):
    goto = loadLongNum()
    ret_reg = getReg()
    regs = loadRegistersArray()
    assert len(regs) % 2 == 0
    add((13,))  # push
    for i in range(0, len(regs), 2):
        add((30, regs[i], regs[i+1]))  # {dst} = {src}
    add([31, ret_reg, goto])  # {ret_reg} = call {goto}
    queue.append(goto)
    return 0

def op_14(add):
    result_reg = getReg()
    regs = loadRegistersArray().expandleft(result_reg)
    add((14, regs))  # return
    return EOB

def op_15(add):
    dst = getReg()
    src = getReg()
    add((15, dst, src))  # {dst} = {src}
    return 0

def op_16(add):
    add((16,))  # HALT
    return EOB
def op_17(add):
    reg = getReg()
    goto = loadLongNum()
    queue.append(pos)
    queue.append(goto)
    add([17, goto, reg, pos])  # goto {goto} if {reg} else {pos}
    return EOB
def op_18(add):
    goto = loadLongNum()
    queue.append(goto)
    add([18, goto])  # goto {goto}
    return EOB
def op_19(add):
    reg = getReg()
    goto = loadLongNum()
    queue.append(pos)
    queue.append(goto)
    add([17, pos, reg, goto])  # goto {pos} if {reg} else {goto}
    return EOB

def op_20(add):
    reg = getReg()
    goto = loadLongNum()
    args = loadRegistersArray()
    queue.append(goto)
    add([20, reg, goto, args])
    return 0

def op_21(add):
    arr_reg = getReg()
    idx_reg = getReg()
    val_reg = getReg()
    add((21, RegSetItem(arr_reg, idx_reg, val_reg)))  # {arr_reg}[{idx_reg}] = {val_reg}
    return 0

# 22 - catch
# 23 - throw

def op_50(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, "==", R)))
    return 0
def op_51(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, "!=", R)))
    return 0
def op_52(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, "===", R)))
    return 0
def op_53(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, "!==", R)))
    return 0
def op_54(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, '<', R)))
    return 0
def op_55(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, '>', R)))
    return 0
def op_56(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, "<=", R)))
    return 0
def op_57(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((50, reg, BinOp(L, ">=", R)))
    return 0

def op_100(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((100, reg, BinOp(L, '+', R)))
    return 0
def op_101(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((100, reg, BinOp(L, '*', R)))
    return 0
def op_102(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((100, reg, BinOp(L, '-', R)))
    return 0
def op_103(add):
    reg = getReg()
    L = getReg()
    R = getReg()
    add((100, reg, BinOp(L, '/', R)))
    return 0


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
    void = lambda _: None

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
            eob = ops[kind](void)
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
            if kind in (20, 31):
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

_id2shift = tuple(1 << i for i in range(256))
def mask2regs(mask):
    return RegArray(Reg(i) for i, shift in enumerate(_id2shift) if mask & shift)
def live_variables(FF):
    blocks, preds, succs, calls = FF
    gens, kills = {}, {}
    TOP = (1 << 256) - 1
    for bb, insts in blocks.items():
        GEN = KILL = 0
        for inst in insts:
            kind = inst[0]
            if HAS_LHS[kind]:
                KILL |= _id2shift[inst[1].id]
            idx = HAS_USES[kind]
            if idx is not None:
                uses = set()
                inst[idx].uses(uses.add)
                for reg in uses:
                    shift = _id2shift[reg.id]
                    if not KILL & shift:
                        GEN |= shift
        gens[bb] = GEN
        kills[bb] = ~KILL & TOP

    IN = {bb: 0 for bb in blocks}
    OUT = {bb: 0 for bb in blocks}
    changed = True
    while changed:
        changed = False
        for bb in blocks:
            new_OUT = 0
            for succ in succs.get(bb, set()):
                new_OUT |= IN[succ]
            # IN[bb] = GEN[bb] | (OUT[bb] & ~KILL[bb])
            new_IN = gens[bb] | (new_OUT & kills[bb])

            if new_OUT != OUT[bb] or new_IN != IN[bb]:
                OUT[bb] = new_OUT
                IN[bb] = new_IN
                changed = True

    for bb, insts in blocks.items():
        print("GEN:", mask2regs(gens[bb]))
        print("KILL:", mask2regs(~kills[bb] & TOP))
        print("IN:", mask2regs(IN[bb]))
        print("OUT:", mask2regs(OUT[bb]))
        print(bb2str(bb, insts))
    exit()


def call_blocks(insts):
    result = set()
    for inst in insts:
        kind = inst[0]
        if kind in (20, 31):
            result.add(inst[2])
    return result

RED    = "\33[91m"
GREEN  = "\33[92m"
YELLOW = "\33[93m"
RESET  = "\33[0m"
def print_colored_set(_set, blocks, calls):
    buffer = StringIO()
    write = buffer.write
    write('{')
    for i, bb in enumerate(_set):
        if i:
            write(", ")
        _input = bool(calls[bb])
        output = bool(call_blocks(blocks[bb]))
        color = YELLOW if _input and output else GREEN if _input else RED if output else None
        write(str(bb) if color is None else f"{color}{bb}{RESET}")
    write('}')
    return buffer.getvalue()

def get_cycles(FF):
    def dfs(bb):
        visited = {bb}
        queue = deque()
        queue.append(bb)
        while queue:
            bb = queue.popleft()
            for succ_bb in succs[bb]:
                if succ_bb not in visited:
                    visited.add(succ_bb)
                    queue.append(succ_bb)
            for pred_bb in preds[bb]:
                if pred_bb not in visited:
                    visited.add(pred_bb)
                    queue.append(pred_bb)
        return visited

    blocks, preds, succs, calls = FF
    visited = set()
    cycles = []
    for bb in blocks:
        if bb not in visited:
            cycle = dfs(bb)
            visited |= cycle
            cycles.append(cycle)
    print("|cycles|:", len(cycles))
    for cycle in cycles:
        all_calls = set()
        for bb in cycle:
            all_calls |= calls[bb]
        print(all_calls, "->", print_colored_set(cycle, blocks, calls))

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
            eob = ops[kind](add)
            if pos < end_pos:
                assert not eob
        for inst in insts:
            kind = inst[0]
            if kind in (20, 31):
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
    live_variables(FF)
    print_cfg(FF)
    get_cycles(FF)


def main():
    gotos = stage1()
    stage2(gotos)


if __name__ == "__main__":
    main()
