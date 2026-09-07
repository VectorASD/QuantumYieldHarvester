from struct import unpack
from collections import deque
from pathlib import Path
from base64 import b64decode
import re

from .ir import _regbase
from .ir import RegIndex, RegArray, RegCall, BinOp, LambdaDef, CallDef
from .ir import Statement, AssignStatement, SetItemStatement, HaltStatement, ReturnStatement, GotoStatement, CondStatement, JumpStatement


class Block:
    def __init__(self, id):
        self.id = id
    def __repr__(self):
        return f"BB{self.id}"
    def __eq__(self, right):
        return isinstance(right, Block) and self.id == right.id
    def __hash__(self):
        return hash(self.id)
    def __lt__(self, right):
        if isinstance(right, Block):
            return self.id < right.id
        return NotImplemented


def make_parser():
    bytecode: bytes = b""
    pos:      int   = 0
    queue:    deque = deque()

    def getByte():
        nonlocal pos
        byte = bytecode[pos]; pos += 1
        return byte

    def getReg():
        return _regbase[getByte()]

    def loadLongNum():
        nonlocal pos
        num: int = unpack(">I", bytecode[pos:pos+4])[0]
        pos += 4
        return num

    def loadString():
        nonlocal pos
        size = unpack(">H", bytecode[pos:pos+2])[0]; pos += 2
        str = ''.join(map(chr, bytecode[pos:pos+size]))
        pos += size
        return str

    def loadFloat():
        nonlocal pos
        num: float = unpack(">d", bytecode[pos:pos+8])[0]
        pos += 8
        return num

    def loadRegistersArray():
        nonlocal pos
        size = bytecode[pos]; pos += 1
        array = RegArray(_regbase[byte] for byte in bytecode[pos:pos+size])
        pos += size
        return array


    EOB = True  # end of block

    def op_1(add):
        reg = getReg()
        str = loadString()
        add(AssignStatement(reg, str))  # {reg} = {str!r}
        return 0
    def op_2(add):
        reg = getReg()
        num = getByte()
        add(AssignStatement(reg, num))  # {reg} = {num}
        return 0
    def op_3(add):
        reg = getReg()
        num = loadFloat()
        add(AssignStatement(reg, num))  # {reg} = {num}
        return 0
    def op_4(add):
        reg = getReg()
        num = loadLongNum()
        add(AssignStatement(reg, num))  # {reg} = {num}
        return 0
    def op_5(add):
        reg = getReg()
        arr = loadRegistersArray()
        add(AssignStatement(reg, arr))  # {reg} = {arr}
        return 0

    def op_10(add):
        set_reg = getReg()
        arr_reg = getReg()
        idx_reg = getReg()
        add(AssignStatement(set_reg, RegIndex(arr_reg, idx_reg)))  # {set_reg} = {arr_reg}[{idx_reg}]]
        return 0

    def op_11(add):
        set_reg = getReg()
        func_reg = getReg()
        this_reg = getReg()
        args = loadRegistersArray()
        # {set_reg} = {func_reg}.apply({this_reg}, {args})
        add(AssignStatement(set_reg, RegCall(func_reg, this_reg, args)))
        return 0

    # 12 - eval

    def op_13(add):
        goto = loadLongNum()
        ret_reg = getReg()
        regs = loadRegistersArray()
        assert len(regs) % 2 == 0
        dsts = tuple(regs[i]  for i in range(0, len(regs), 2))
        srcs = list(regs[i+1] for i in range(0, len(regs), 2))
        add(AssignStatement(ret_reg, CallDef(goto, dsts, srcs)))  # {ret_reg} = call {goto} ({args})
        queue.append(goto)
        return 0

    def op_14(add):
        ret_reg = getReg()
        closure = loadRegistersArray()
        add(ReturnStatement(ret_reg, closure))  # return <ret_reg>  // closure: <closure>
        return EOB

    def op_15(add):
        dst = getReg()
        src = getReg()
        add(AssignStatement(dst, src))  # {dst} = {src}
        return 0

    def op_16(add):
        add(HaltStatement())  # HALT
        return EOB
    def op_17(add):
        reg = getReg()
        goto = loadLongNum()
        queue.append(pos)
        queue.append(goto)
        add(CondStatement(goto, reg, pos))  # goto {goto} if {reg} else {pos}
        return EOB
    def op_18(add):
        goto = loadLongNum()
        queue.append(goto)
        add(GotoStatement(goto))  # goto {goto}
        return EOB
    def op_19(add):
        reg = getReg()
        goto = loadLongNum()
        queue.append(pos)
        queue.append(goto)
        add(CondStatement(pos, reg, goto))  # goto {pos} if {reg} else {goto}
        return EOB

    def op_20(add):
        reg = getReg()
        goto = loadLongNum()
        args = loadRegistersArray()
        queue.append(goto)
        add(AssignStatement(reg, LambdaDef(goto, args)))
        return 0

    def op_21(add):
        arr_reg = getReg()
        idx_reg = getReg()
        val_reg = getReg()
        add(SetItemStatement(arr_reg, idx_reg, val_reg))  # {arr_reg}[{idx_reg}] = {val_reg}
        return 0

    # 22 - catch
    # 23 - throw

    def op_50(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, "==", R)))
        return 0
    def op_51(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, "!=", R)))
        return 0
    def op_52(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, "===", R)))
        return 0
    def op_53(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, "!==", R)))
        return 0
    def op_54(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '<', R)))
        return 0
    def op_55(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '>', R)))
        return 0
    def op_56(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, "<=", R)))
        return 0
    def op_57(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, ">=", R)))
        return 0

    def op_100(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '+', R)))
        return 0
    def op_101(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '*', R)))
        return 0
    def op_102(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '-', R)))
        return 0
    def op_103(add):
        reg = getReg()
        L = getReg()
        R = getReg()
        add(AssignStatement(reg, BinOp(L, '/', R)))
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


    def stage1(init_bytecode: bytes, start_pos: int = 0):
        nonlocal pos, bytecode
        bytecode = init_bytecode

        visited = [False] * len(bytecode)
        subprograms = set()  # proper subprogram entry points
        gotos: set[int] = set()  # all jump targets, even into the middle of a subprogram
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
                    print("unknown kind:", kind)
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

    def stage2(gotos):
        nonlocal pos

        _range = range(len(bytecode))
        for goto in gotos:
            assert goto in _range

        gotos.add(len(bytecode))
        gotos = sorted(gotos)
        goto2bb = {goto: Block(i) for i, goto in enumerate(gotos)}
        blocks: dict[Block, list[Statement]] = {}

        for i in range(len(gotos) - 1):
            start_pos = pos = gotos[i]
            end_pos = gotos[i+1]
            insts = blocks[goto2bb[start_pos]] = []
            add = insts.append
            while pos < end_pos:
                kind = getByte()
                eob = ops[kind](add)
                if pos < end_pos:
                    assert not eob
            for inst in insts:
                expr = inst.expr
                if isinstance(expr, CallDef|LambdaDef):
                    expr.goto = goto2bb[expr.goto]
            if not eob:
                add(GotoStatement(pos))  # goto {pos}

            term_inst = insts[-1]
            if isinstance(term_inst, JumpStatement):
                term_inst.target = goto2bb[term_inst.target]
                if isinstance(term_inst, CondStatement):
                    term_inst.fall = goto2bb[term_inst.fall]
        return blocks

    def parse_it(bytecode: bytes):
        gotos = stage1(bytecode)
        blocks = stage2(gotos)
        return blocks
    return parse_it


def print_op_14(write, inst):
    """Not used. This is just a concept/pseudocode, i.e., what actually happens in the VM."""
    _, return_reg = inst
    write(" 14 | _regs, ret_reg = reg_backups.pop()\n")
    write(f"      _regs[ret_reg] = {return_reg.reg}\n")
    if return_reg.closure:
        write(f"      mod_regs |= {set(return_reg.closure)}\n")
    write("      _regs[mod_regs] = regs[mod_regs]\n")
    write("      if len(reg_backups) == 0: mod_regs.clear()\n")
    write("      regs = _regs\n")


def load_bytecode(path: Path) -> bytes:
    match = re.search(rb'a\.init\(\s*"([A-Za-z0-9+/=]+)"', path.read_bytes())
    if not match:
        raise RuntimeError("Bytecode string not found")
    bytecode = b64decode(match.group(1))
    # print(len(bytecode))  # 28728
    return bytecode

def parse_bytecode(path: Path) -> dict[Block, list[Statement]]:
    bytecode = load_bytecode(path)
    parse_it = make_parser()
    return parse_it(bytecode)
