from base64 import b64decode
from struct import unpack
from collections import deque, defaultdict
from pathlib import Path
import re
from io import StringIO


bytecode_path = Path(__file__).parent / "polygon" / "challenge2.js"
match = re.search(rb'a\.init\(\s*"([A-Za-z0-9+/=]+)"', bytecode_path.read_bytes())
if not match:
    raise RuntimeError("Bytecode string not found")
bytecode = b64decode(match.group(1))
# print(len(bytecode))  # 28728

class Undefined:
    def __repr__(self):
        return "undefined"
class Null:
    def __repr__(self):
        return "null"

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

type Const = str | int | float

class Expression:
    def replace(self, get):
        return self
    def evaluate(self):
        """Returns either None or {"value": evaluated}."""
        pass
    def traverse(self, get):
        visitor = get(type(self))
        if visitor:
            visitor(self)
    def chain(self):
        pass

class Reg(Expression):
    def __init__(self, id):
        self.id = id
    def __repr__(self):
        id = self.id
        name = reg_names[id]
        return f"reg{id}" if name is None else name
    def __eq__(self, right):
        return isinstance(right, Reg) and self.id == right.id
    def __hash__(self):
        return hash(self.id)
    def __lt__(self, right):
        if isinstance(right, Reg):
            return self.id < right.id
        return NotImplemented
    def uses(self, add):
        add(self)
    def replace(self, get):
        return get(self, self)
    def chain(self):
        return self
_regbase = tuple(Reg(id) for id in range(256))
_name2reg = {name: _regbase[id] for id, name in enumerate(reg_names) if name is not None}

class RegIndex(Expression):
    def __init__(self, reg, index):
        self.reg = reg
        self.index = index
    def __repr__(self):
        index = self.index
        if isinstance(index, str) and index.isidentifier():
            return f"{self.reg!r}.{index}"
        return f"{self.reg!r}[{index!r}]"
    def uses(self, add):
        reg, index = self.reg, self.index
        if isinstance(reg, Expression):
            reg.uses(add)
        if isinstance(index, Expression):
            index.uses(add)
    def replace(self, get):
        if isinstance(self.reg, Expression):
            self.reg = self.reg.replace(get)
        if isinstance(self.index, Expression):
            self.index = self.index.replace(get)
        return self
    def traverse(self, get):
        Expression.traverse(self, get)
        if isinstance(self.reg, Expression):
            self.reg.traverse(get)
        if isinstance(self.index, Expression):
            self.index.traverse(get)
    def chain(self):
        reg = self.reg.chain() if isinstance(self.reg, Expression) else self.reg
        index = self.index.chain() if isinstance(self.index, Expression) else self.index
        if reg is not None and index is not None:
            if isinstance(reg, tuple):
                return (*reg, index)
            return (reg, index)

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
    def replace(self, get):
        new_items = tuple(
            item.replace(get) if isinstance(item, Expression) else item
            for item in self.items
        )
        self.items = new_items
        return self
    def traverse(self, get):
        Expression.traverse(self, get)
        for item in self.items:
            if isinstance(item, Expression):
                item.traverse(get)

class RegCall(Expression):
    def __init__(self, func, this, args):
        self.func = func
        self.this = this
        self.args = args  # RegArray
    def __repr__(self):
        if self.this is None:
            return f"{self.func}({str(self.args)[1:-1]})"
        return f"{self.func!r}.apply({self.this!r}, {self.args})"
    def uses(self, add):
        if isinstance(self.func, Expression):
            self.func.uses(add)
        if isinstance(self.this, Expression):
            self.this.uses(add)
        self.args.uses(add)
    def replace(self, get):
        if isinstance(self.func, Expression):
            self.func = self.func.replace(get)
        if isinstance(self.this, Expression):
            self.this = self.this.replace(get)
        self.args.replace(get)
        return self
    def evaluate(self):
        func = self.func
        if isinstance(func, Reg) and func.id == 0:
            assert isinstance(self.this, Undefined)
            args = self.args
            assert len(args) == 3
            assert isinstance(args[0], int)
            return {"value": Caesar(*args)}
    def traverse(self, get):
        Expression.traverse(self, get)
        if isinstance(self.func, Expression):
            self.func.traverse(get)
        if isinstance(self.this, Expression):
            self.this.traverse(get)
        self.args.traverse(get)

class BinOp(Expression):
    _evaluator = {
        '==': lambda L, R: L == R,
        '!=': lambda L, R: L != R,
      # '===': lambda L, R: type(L) is type(R) and L == R,
      # '!==': lambda L, R: type(L) is type(R) and L != R,
        '>': lambda L, R: L > R,
        '<': lambda L, R: L < R,
        '>=': lambda L, R: L >= R,
        '<=': lambda L, R: L <= R,
        '+': lambda L, R: L + R,
        '-': lambda L, R: L - R,
        '*': lambda L, R: L * R,
        '/': lambda L, R: L / R if R else float("inf"),
    }
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right
        self.isarith = op in ('+', '-', '*', '/')
    def __repr__(self):
        return f"{self.left!r} {self.op} {self.right!r}"
    def uses(self, add):
        if isinstance(self.left, Expression):
            self.left.uses(add)
        if isinstance(self.right, Expression):
            self.right.uses(add)
    def replace(self, get):
        if isinstance(self.left, Expression):
            self.left = self.left.replace(get)
        if isinstance(self.right, Expression):
            self.right = self.right.replace(get)
        return self
    def evaluate(self):
        if isinstance(self.left, int) and isinstance(self.right, int):
            return {"value": BinOp._evaluator[self.op](self.left, self.right)}
    def traverse(self, get):
        Expression.traverse(self, get)
        if isinstance(self.left, Expression):
            self.left.traverse(get)
        if isinstance(self.right, Expression):
            self.right.traverse(get)

class LambdaDef(Expression):
    def __init__(self, goto, args):
        self.goto = goto
        self.args = args  # RegArray
    def __repr__old__(self):
        """Not used. This is just a concept/pseudocode, i.e., what actually happens in the VM."""
        buffer = StringIO()
        write = buffer.write
        write("function() {\n")
        if self.args:
            write(f"        {str(self.args)[1:-1]} = arguments\n")
        write(f"        reg_backups.push([regs[:], {_regbase[201]!r})\n")
        write(f"        call {self.goto} while !{_regbase[201]}\n")
        write(f"        return (delete {_regbase[201]})\n")
        write("      }")
        return buffer.getvalue()
    def __repr__(self):
        if self.args:
            return f"lambda *a: call {self.goto} ({self.args} = a)"
        return f"lambda: call {self.goto} ()"
    def uses(self, add):
        pass
    def traverse(self, get):
        Expression.traverse(self, get)
        self.args.traverse(get)

class CallDef(Expression):
    def __init__(self, goto, dsts: tuple[Expression], srcs: list[Expression]):
        self.goto = goto
        self.dsts = dsts
        self.srcs = srcs
        assert len(dsts) == len(srcs)
    def __repr__(self):
        args = ", ".join(f'{dst} = {src}' for dst, src in zip(self.dsts, self.srcs))
        return f"call {self.goto} ({args})"
    def uses(self, add):
        for src in self.srcs:
            if isinstance(src, Expression):
                src.uses(add)
    def replace(self, get):
        srcs = self.srcs
        for i, src in enumerate(srcs):
            if isinstance(src, Expression):
                srcs[i] = src.replace(get)
        return self
    def traverse(self, get):
        Expression.traverse(self, get)
        for src in self.srcs:
            if isinstance(src, Expression):
                src.traverse(get)

CallExpression = CallDef | LambdaDef

class InverseReg(Expression):
    def __init__(self, reg: Expression | Const):
        self.reg = reg
    def __repr__(self):
        if isinstance(self.reg, LambdaDef | BinOp):
            return f"!({self.reg})"
        return f"!{self.reg}"
    def uses(self, add):
        if isinstance(self.reg, Expression):
            self.reg.uses(add)
    def replace(self, get):
        if isinstance(self.reg, Expression):
            self.reg = self.reg.replace(get)
        return self
    def traverse(self, get):
        Expression.traverse(self, get)
        if isinstance(self.reg, Expression):
            self.reg.traverse(get)


class Statement:
    isconst = False
    expr = None
    def uses(self, add):
        pass
    def replace(self, get):
        return self
    def evaluate(self):
        pass
    def traverse(self, get):
        visitor = get(type(self))
        if visitor:
            visitor(self)

class AssignStatement(Statement):
    def __init__(self, reg: Reg, expr: Expression|Const):
        self.reg = reg
        self.expr = expr
        self.isconst = not isinstance(expr, Expression)
    def __repr__(self, pad=""):
        expr = self.expr
        if isinstance(expr, BinOp) and expr.isarith and expr.left == self.reg:
            if expr.right == 1 and expr.op in ('+', '-'):
                return f"{pad}{self.reg}{expr.op}{expr.op}"  # ++, --
            return f"{pad}{self.reg} {expr.op}= {expr.right!r}"  # +=, -=, *=, /=
        return f"{pad}{self.reg} = {expr!r}"
    def uses(self, add):
        if isinstance(self.expr, Expression):
            self.expr.uses(add)
    def replace(self, get):
        if isinstance(self.expr, Expression):
            self.expr = self.expr.replace(get)
        return self
    def evaluate(self):
        if isinstance(self.expr, Expression):
            return self.expr.evaluate()
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.expr, Expression):
            self.expr.traverse(get)

class SetItemStatement(Statement):
    def __init__(self, obj: Expression|Const, index, value):
        self.obj = obj
        self.index = index
        self.value = value
    def __repr__(self, pad=""):
        return f"{pad}{self.obj!r}[{self.index!r}] = {self.value!r}"
    def uses(self, add):
        for part in (self.obj, self.index, self.value):
            if isinstance(part, Expression):
                part.uses(add)
    def replace(self, get):
        for attr in ('obj', 'index', 'value'):
            part = getattr(self, attr)
            if isinstance(part, Expression):
                setattr(self, attr, part.replace(get))
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        for attr in ('obj', 'index', 'value'):
            part = getattr(self, attr)
            if isinstance(part, Expression):
                part.traverse(get)

class HaltStatement(Statement):
    def __repr__(self, pad=""):
        return f"{pad}HALT"

class ReturnStatement(Statement):
    def __init__(self, reg: Expression|Const, closure: RegArray):
        self.reg = reg
        self.closure = closure
        self.dcm = {}  # default_const_map
    def __repr__(self, pad=""):
        if isinstance(self.dcm.get(self.reg), Undefined):
            return f"{pad}return  // closure: {sorted(self.closure)}"
        return f"{pad}return {self.reg}  // closure: {sorted(self.closure)}"
    def uses(self, add):
        if isinstance(self.reg, Expression):
            self.reg.uses(add)
    def uses_fd(self, add):
        if isinstance(self.reg, Expression):
            self.reg.uses(add)
        self.closure.uses(add)
    def replace(self, get):
        if isinstance(self.reg, Expression):
            self.reg = self.reg.replace(get)
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.reg, Expression):
            self.reg.traverse(get)
        self.closure.traverse(get)

class GotoStatement(Statement):
    def __init__(self, target):
        self.target = target
    def __repr__(self, pad=""):
        return f"{pad}goto {self.target}"

class CondStatement(Statement):
    def __init__(self, target, condition: Expression|Const, fall):
        self.target = target
        self.cond = condition
        self.fall = fall
    def __repr__(self, pad=""):
        return f"{pad}goto {self.target} if {self.cond} else {self.fall}"
    def uses(self, add):
        if isinstance(self.cond, Expression):
            self.cond.uses(add)
    def replace(self, get):
        if isinstance(self.cond, Expression):
            self.cond = self.cond.replace(get)
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.cond, Expression):
            self.cond.traverse(get)

JumpStatement = GotoStatement | CondStatement


class IfStatement(Statement):
    def __init__(self, condition: Expression|Const, then_stmts: list[Statement], else_stmts: list[Statement]|None = None):
        self.cond = condition
        self.then_stmts = then_stmts
        self.else_stmts = else_stmts or ()
    def __repr__(self, pad=""):
        next_pad = pad + "  "
        then_stmts, else_stmts = self.then_stmts, self.else_stmts
        buffer = StringIO()
        write = buffer.write
        write(f"{pad}if ({self.cond!r})")
        if not then_stmts:
            write(" {}")
            if else_stmts:
                write(f"\n{pad}else")
        elif len(then_stmts) == 1:
            write(f"\n{then_stmts[0].__repr__(pad=next_pad)}")
            if else_stmts:
                write(f"\n{pad}else")
        else:
            write(" {\n")
            for stmt in then_stmts:
                write(f"{stmt.__repr__(pad=next_pad)}\n")
            write(f"{pad}}}")
            if else_stmts:
                write(" else")
        if else_stmts:
            if len(else_stmts) == 1:
                write(f"\n{else_stmts[0].__repr__(pad=next_pad)}")
            else:
                write(" {\n")
                for stmt in else_stmts:
                    write(f"{stmt.__repr__(pad=next_pad)}\n")
                write(f"{pad}}}")
        return buffer.getvalue()
    def uses(self, add):
        if isinstance(self.cond, Expression):
            self.cond.uses(add)
        for stmt in self.then_stmts:
            stmt.uses(add)
        if self.else_stmts:
            for stmt in self.else_stmts:
                stmt.uses(add)
    def replace(self, get):
        if isinstance(self.cond, Expression):
            self.cond = self.cond.replace(get)
        for stmt in self.then_stmts:
            stmt.replace(get)
        if self.else_stmts:
            for stmt in self.else_stmts:
                stmt.replace(get)
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.cond, Expression):
            self.cond.traverse(get)
        for stmt in self.then_stmts:
            stmt.traverse(get)
        if self.else_stmts:
            for stmt in self.else_stmts:
                stmt.traverse(get)

class WhileStatement(Statement):
    def __init__(self, cond: Expression|Const, body: list[Statement]):
        self.cond = cond
        self.body = body
    def __repr__(self, pad=""):
        next_pad = pad + "  "
        body = self.body
        buffer = StringIO()
        write = buffer.write
        write(f"{pad}while ({self.cond!r})")
        if not body:
            write(" {}")
        elif len(body) == 1:
            write(f"\n{body[0].__repr__(pad=next_pad)}")
        else:
            write(" {\n")
            for stmt in body:
                write(f"{stmt.__repr__(pad=next_pad)}\n")
            write(f"{pad}}}")
        return buffer.getvalue()
    def uses(self, add):
        if isinstance(self.cond, Expression):
            self.cond.uses(add)
        for stmt in self.body:
            stmt.uses(add)
    def replace(self, get):
        if isinstance(self.cond, Expression):
            self.cond = self.cond.replace(get)
        for stmt in self.body:
            stmt.replace(get)
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.cond, Expression):
            self.cond.traverse(get)
        for stmt in self.body:
            stmt.traverse(get)

class DoWhileStatement(Statement):
    def __init__(self, cond: Expression|Const, body: list[Statement]):
        self.cond = cond
        self.body = body
    def __repr__(self, pad=""):
        next_pad = pad + "  "
        body = self.body
        buffer = StringIO()
        write = buffer.write
        write(f"{pad}do")
        if not body:
            write(" {}\n")
            write(pad)
        elif len(body) == 1:
            write(f"\n{body[0].__repr__(pad=next_pad)}\n")
            write(pad)
        else:
            write(" {\n")
            for stmt in body:
                write(f"{stmt.__repr__(pad=next_pad)}\n")
            write(pad)
            write("} ")
        write(f"while ({self.cond!r})")
        return buffer.getvalue()
    def uses(self, add):
        if isinstance(self.cond, Expression):
            self.cond.uses(add)
        for stmt in self.body:
            stmt.uses(add)
    def replace(self, get):
        if isinstance(self.cond, Expression):
            self.cond = self.cond.replace(get)
        for stmt in self.body:
            stmt.replace(get)
        return self
    def traverse(self, get):
        Statement.traverse(self, get)
        if isinstance(self.cond, Expression):
            self.cond.traverse(get)
        for stmt in self.body:
            stmt.traverse(get)


def check_printers():
    for i in range(3):
        for j in range(3):
            print()
            print(IfStatement(123, [HaltStatement()] * i, [HaltStatement()] * j).__repr__(pad=f"{i}{j}  "))
    for i in range(3):
        print()
        print(WhileStatement(123, [HaltStatement()] * i).__repr__(pad=f"{i} "))
    for i in range(3):
        print()
        print(DoWhileStatement(123, [HaltStatement()] * i).__repr__(pad=f"{i} "))
    exit()
# check_printers()


def getByte():
    global pos
    byte = bytecode[pos]; pos += 1
    return byte

def getReg():
    return _regbase[getByte()]

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
    array = RegArray(_regbase[byte] for byte in bytecode[pos:pos+size])
    pos += size
    return array

def Caesar(shift, right, left):
    eval = (left + right).strip()
    assert eval[0] == '[' and eval[-1] == ']'
    return ''.join(chr(int(part) - shift) for part in eval[1:-1].split(',') if part.strip())

# print(Caesar(8, '5,]', '[10'))
# print(Caesar(7, '105,53,119,124,122,111,47,104,53,106,111,104,121,74,118,107,108,72,123,47,112,48,48,66,121,108,123,124,121,117,39,105,]', '[125,104,121,39,112,68,55,51,105,68,98,100,66,109,118,121,47,66,112,67,104,53,115,108,117,110,123,111,66,112,50,50,48,'))
# exit()


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

def bb2str(bb, insts):
    buffer = StringIO()
    write = buffer.write
    write(f"~~~ {bb}\n")
    pad = "  "
    for inst in insts:
        write(f"{inst.__repr__(pad=pad)}\n")
    return buffer.getvalue()
def print_cfg(FF, DF_LV=None):
    blocks, preds, succs, calls = FF
    if DF_LV is not None:
        GEN, KILL, IN, OUT = DF_LV
    for bb, insts in blocks.items():
        if SKIP_BLOCKS_WITH_CFG and not preds[bb] and not succs[bb]:
            continue
        if DF_LV is not None:
          # print("GEN:", mask2regs(GEN[bb]))
          # print("KILL:", mask2regs(KILL[bb]))
            print("IN:", mask2regs(IN[bb]))
            print("OUT:", mask2regs(OUT[bb]))
        bb_name = (str(bb), f"  // preds: {preds[bb]}" if preds[bb] else '', f"  // calls: {calls[bb]}" if calls[bb] else '')
        print(bb2str(''.join(bb_name), insts))


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

queue = deque()
def stage1(start_pos=0):
    global pos

    visited = [False] * len(bytecode)
    subprograms = set()  # proper subprogram entry points
    gotos = set()  # all jump targets, even into the middle of a subprogram
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

def make_cfg(blocks):
    succs = {bb: set() for bb in blocks}
    calls = {bb: set() for bb in blocks}
    def call_traverse(node):
        calls[node.goto].add(bb)
    traverse = {call_type: call_traverse for call_type in CallExpression.__args__}.get
    for bb, insts in blocks.items():
        for inst in insts:
            inst.traverse(traverse)
        term_inst = insts[-1]
        if isinstance(term_inst, JumpStatement):
            succs[bb].add(term_inst.target)
            if isinstance(term_inst, CondStatement):
                succs[bb].add(term_inst.fall)

    preds = {bb: [] for bb in blocks}
    for bb, bb_succ in succs.items():
        for succ in bb_succ:
            preds[succ].append(bb)
    return blocks, preds, succs, calls

def check_cfg(FF):
    blocks, old_preds, old_succs, old_calls = FF
    _, preds, succs, calls = make_cfg(blocks)
    errors = []
    for bb in blocks:
        if sorted(old_preds[bb]) != sorted(preds[bb]):
            errors.append(f"preds[{bb}]:\n    actual: {old_preds[bb]}\n    expected: {preds[bb]}")
        if old_succs[bb] != succs[bb]:
            errors.append(f"succs[{bb}]:\n    actual: {old_succs[bb]}\n    expected: {succs[bb]}")
        if old_calls[bb] != calls[bb]:
            errors.append(f"calls[{bb}]:\n    actual: {old_calls[bb]}\n    expected: {calls[bb]}")
    print(*errors, sep='\n')
    if errors:
        exit()

def clean_insts(insts):
    try: pos = insts.index(None)
    except ValueError: return
    for i in range(pos+1, len(insts)):
        item = insts[i]
        if item is not None:
            insts[pos] = item
            pos += 1
    pop = insts.pop
    for i in range(len(insts) - pos):
        pop()

def check_users(FF):
    blocks = FF[0]
    users = set(); add = users.add
    for insts in blocks.values():
        for inst in insts:
            if isinstance(inst, AssignStatement):
                add(inst.reg)
    const_regs = set(str(reg) for reg in _regbase if reg not in users)
    defaults = {"c0": 0, "c1": 1, "(void 0)": Undefined(), "null": Null()}
    default_const_map = {_name2reg[k]: v for k, v in defaults.items() if k in const_regs}
    print("\nconst regs:", const_regs)
    print("default const map:", default_const_map)
    for insts in blocks.values():
        term_inst = insts[-1]
        if isinstance(term_inst, ReturnStatement):
            term_inst.dcm = default_const_map
    return default_const_map


_id2shift = tuple(1 << i for i in range(256))
def mask2regs(mask):
    return RegArray(_regbase[i] for i, shift in enumerate(_id2shift) if mask & shift)
def LiveVariables(FF):
    blocks, preds, succs, calls = FF
    GEN, KILL, _KILL = {}, {}, {}
    TOP = (1 << 256) - 1
    for bb, insts in blocks.items():
        gen = kill = 0
        for inst in insts:
            if isinstance(inst, AssignStatement):
                kill |= _id2shift[inst.reg.id]
            uses = set()
            (inst.uses_fd if isinstance(inst, ReturnStatement) else inst.uses)(uses.add)
            for reg in uses:
                shift = _id2shift[reg.id]
                if not kill & shift:
                    gen |= shift
        GEN[bb] = gen
        KILL[bb] = kill
        _KILL[bb] = ~kill & TOP

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
            new_IN = GEN[bb] | (new_OUT & _KILL[bb])

            if new_OUT != OUT[bb] or new_IN != IN[bb]:
                OUT[bb] = new_OUT
                IN[bb] = new_IN
                changed = True

    return GEN, KILL, IN, OUT

def ConstantPropogationAndFolding(FF, DF_LV, default_const_map):
    blocks = FF[0]
    OUT = DF_LV[3]
    for bb, insts in blocks.items():
        out = OUT[bb]
        const_map = default_const_map.copy()
        for i, inst in enumerate(insts):
            if inst.isconst:  # <reg> = <const>
                const_map[inst.reg] = inst.expr
                if not (out & _id2shift[inst.reg.id]):
                    insts[i] = None
                continue
            inst.replace(const_map.get)
            result = inst.evaluate()
            if result is not None:
                const_map[inst.reg] = result["value"]
                if not (out & _id2shift[inst.reg.id]):
                    insts[i] = None
        if const_map:
            clean_insts(insts)

def ForwardSubstitution(FF, DF_LV):
    """Do not call a second time, otherwise we will with `100% probability` break the original execution order of instructions!"""
    blocks = FF[0]
    OUT = DF_LV[3]
    def add(name):
        counter[name] += 1
    for bb, insts in blocks.items():
        counter = defaultdict(int)
        for inst in insts:
            inst.uses(add)
        for name in mask2regs(OUT[bb]):
            counter[name] += 1

        need_clean = False
        for i, inst in enumerate(insts):
            prev_i = i - 1
            if prev_i < 0 or not isinstance(insts[prev_i], AssignStatement):
                continue
            uses = []
            inst.uses(uses.append)
            prev_inst: AssignStatement = insts[prev_i]
            replaces = {}
            for reg in reversed(uses):
                if isinstance(reg, Reg) and counter[reg] == 1 and reg == prev_inst.reg:
                    replaces[reg] = prev_inst.expr
                    insts[prev_i] = None
                    prev_i -= 1
                    while prev_i >= 0 and insts[prev_i] is None:
                        prev_i -= 1
                    if prev_i < 0 or not isinstance(insts[prev_i], AssignStatement):
                        break
                    prev_inst = insts[prev_i]
            if replaces:
                inst.replace(replaces.get)
                need_clean = True
        if need_clean:
            clean_insts(insts)

def MethodCallDeapply(FF):
    blocks = FF[0]
    def reg_call_traverse(node):
        func = node.func
        if isinstance(func, RegIndex):
            this = node.this.chain() if isinstance(node.this, Expression) else node.this
            if func.reg.chain() == this:
                # example: (window, 'navigator', 'storage') == (window, 'navigator', 'storage')
                node.this = None
            else:
                # Unusual property of this VM's compiler: the sufficiency of just one property isinstance(func, RegIndex).
                # If this ever happens, it will indicate a change in the compiler.
                # Ideally, in this branch reg_call_traverse should do nothing at all! :)
                raise RuntimeError("MethodCallDeapply: undefined behavior")
    traverse = {RegCall: reg_call_traverse}.get
    for insts in blocks.values():
        for inst in insts:
            inst.traverse(traverse)

SKIP_BLOCKS_WITH_CFG = True

def common_join_cfg(bb, end, fixFF):
    preds, succs, calls, call_dsts = fixFF
    for succ_bb in succs[end]:
        preds[succ_bb] = [bb if pred_bb == end else pred_bb for pred_bb in preds[succ_bb]]

    succs[bb] = succs[end]

    for call_bb in call_dsts[end]:
        calls[call_bb].discard(end)
        calls[call_bb].add(bb)
        call_dsts[bb].add(call_bb)

    del preds[end], succs[end], calls[end]

def join_cfg(bb, middle, end, fixFF):
    preds, succs, calls, call_dsts = fixFF
    for succ_bb in succs[end]:
        preds[succ_bb] = [bb if pred_bb == end else pred_bb for pred_bb in preds[succ_bb]]

    succs[bb] = succs[end]

    for call_bb in (call_dsts[middle] | call_dsts[end]):
        calls[call_bb].discard(middle)
        calls[call_bb].discard(end)
        calls[call_bb].add(bb)
        call_dsts[bb].add(call_bb)

    del preds[middle], succs[middle], calls[middle], preds[end], succs[end], calls[end]

def delete_term(FF, bb):
    blocks, preds, succs, calls = FF
    term = blocks[bb].pop()
    if isinstance(term, GotoStatement):
        succs[bb].remove(term.target)
        preds[term.target].remove(bb)
    elif isinstance(term, CondStatement):
        for target in (term.target, term.fall):
            succs[bb].remove(target)
            preds[target].remove(bb)
    else:
        raise RuntimeError(f"delete_term: unsupported {type(term).__name__!r}")

def add_term(FF, bb, term):
    blocks, preds, succs, calls = FF
    blocks[bb].append(term)
    if isinstance(term, CondStatement):
        for target in (term.target, term.fall):
            succs[bb].add(target)
            preds[target].append(bb)
    else:
        raise RuntimeError(f"add_term: unsupported {type(term).__name__!r}")

def replace_term(FF, bb, term):
    delete_term(FF, bb)
    add_term(FF, bb, term)

def delete_block(FF, bb):
    blocks, preds, succs, calls = FF
    if preds[bb] or calls[bb]:
        raise RuntimeError(f"can't delete this {bb}: preds={preds[bb]}, calls={calls[bb]}")
    delete_term(FF, bb)
    if succs[bb]:
        raise RuntimeError(f"Removing terminator don't release of {bb}: succs={succs[bb]}")
    del blocks[bb], preds[bb], succs[bb], calls[bb]

def StructureReconstruction(FF):  # CFG2AST
    blocks, preds, succs, calls = FF

    call_dsts = {bb: set() for bb in blocks}
    for dst, sources in calls.items():
        for src in sources:
            call_dsts[src].add(dst)
    fixFF = preds, succs, calls, call_dsts

    def update(bb):
        queue.extend(preds[bb])
        queue.append(bb)
        queue.extend(succs[bb])

    def analyze(bb, id):
        if bb.id == id:
            print(bb2str(bb, insts))
            print(bb2str(target, blocks[target]))
            print(bb2str(fall, blocks[fall]))
          # print(succs[target] == {bb}, set(preds[target]) == {bb}, set(preds[fall]) == {bb})

    queue = deque(blocks)
    while queue:
        bb = queue.popleft()
        try: insts = blocks[bb]
        except KeyError: continue
        term_inst = insts[-1]
        if isinstance(term_inst, CondStatement):
            target = term_inst.target
            fall = term_inst.fall
            if target == fall:
                raise RuntimeError("unchecked behavior")
            if succs[target] == {fall} and set(preds[target]) == {bb} and set(preds[fall]) == {bb, target}:
                # bb -> target -> fall
                #   \            ^
                #    \----------/
                assert not calls[target] and not calls[fall]
                # blocks
                cond = insts.pop().cond
                then_stmts = blocks.pop(target)
                then_stmt = then_stmts.pop()
                assert isinstance(then_stmt, GotoStatement) and then_stmt.target == fall
                insts.append(IfStatement(cond, then_stmts))
                insts.extend(blocks.pop(fall))
                # CFG
                join_cfg(bb, target, fall, fixFF)
                update(bb)
            elif succs[fall] == {target} and set(preds[fall]) == {bb} and set(preds[target]) == {bb, fall}:
                # bb -> fall -> target
                #   \          ^
                #    \--------/
                assert not calls[fall] and not calls[target]
                # blocks
                cond = insts.pop().cond
                then_stmts = blocks.pop(fall)
                then_stmt = then_stmts.pop()
                assert isinstance(then_stmt, GotoStatement) and then_stmt.target == target
                insts.append(IfStatement(InverseReg(cond), then_stmts))
                insts.extend(blocks.pop(target))
                # CFG
                join_cfg(bb, fall, target, fixFF)
                update(bb)
            elif not succs[target] and set(preds[target]) == {bb} and set(preds[fall]) == {bb}:
                # bb -> target -> return
                #   \-> fall
                # bb;
                assert not calls[target] and not calls[fall]
                # blocks
                cond = insts.pop().cond
                then_stmts = blocks.pop(target)
                assert isinstance(then_stmts[-1], ReturnStatement)
                insts.append(IfStatement(cond, then_stmts))
                insts.extend(blocks.pop(fall))
                # CFG
                join_cfg(bb, target, fall, fixFF)
                update(bb)
            elif not succs[fall] and set(preds[fall]) == {bb} and set(preds[target]) == {bb}:
                # bb -> fall -> return
                #   \-> target
                # bb;
                assert not calls[fall] and not calls[target]
                # blocks
                cond = insts.pop().cond
                then_stmts = blocks.pop(fall)
                assert isinstance(then_stmts[-1], ReturnStatement)
                insts.append(IfStatement(InverseReg(cond), then_stmts))
                insts.extend(blocks.pop(target))
                # CFG
                join_cfg(bb, fall, target, fixFF)
                update(bb)
            elif succs[target] == {bb} and set(preds[target]) == {bb} and set(preds[fall]) == {bb}:
                #   /-> fall
                # bb -> target
                #  ^          \
                #   \---------/
                assert not calls[target] and not calls[fall]
                # blocks
                cond = insts.pop().cond
                body_stmts = blocks.pop(target)
                body_stmt = body_stmts.pop()
                assert isinstance(body_stmt, GotoStatement) and body_stmt.target == bb
                insts.append(WhileStatement(cond, body_stmts))
                insts.extend(blocks.pop(fall))
                # CFG
                join_cfg(bb, target, fall, fixFF)
                preds[bb].remove(target)
                update(bb)
            elif succs[fall] == {bb} and set(preds[fall]) == {bb} and set(preds[target]) == {bb}:
                raise RuntimeError("unchecked!")
                #   /-> target
                # bb -> fall
                #  ^        \
                #   \-------/
                assert not calls[fall] and not calls[target]
                # blocks
                cond = insts.pop().cond
                body_stmts = blocks.pop(fall)
                body_stmt = body_stmts.pop()
                assert isinstance(body_stmt, GotoStatement) and body_stmt.target == bb
                insts.append(WhileStatement(InverseReg(cond), body_stmts))
                insts.extend(blocks.pop(target))
                # CFG
                join_cfg(bb, fall, target, fixFF)
                preds[bb].remove(fall)
                update(bb)
            elif target == bb and set(preds[fall]) == {bb}:
                # bb -\-> fall
                #  ^  |
                #  \--/
                # blocks
                cond = insts.pop().cond
                blocks[bb] = [DoWhileStatement(cond, insts), *blocks.pop(fall)]
                # CFG
                succs[bb].remove(bb)
                preds[bb].remove(bb)
                common_join_cfg(bb, fall, fixFF)
                update(bb)
            elif len(insts) == 1:
                # preds -> bb (single cond) -> target
                #                          \-> fall
                update(bb)
                term = insts[-1]
                for pred in preds[bb]:
                    pred_term = blocks[pred][-1]
                    if isinstance(pred_term, GotoStatement):
                        replace_term(FF, pred, term)
                if not preds[bb] and not calls[bb]:
                    delete_block(FF, bb)
        elif isinstance(term_inst, GotoStatement):
            target = term_inst.target
            if set(preds[target]) == {bb}:
                # bb -> target
                assert not calls[target]
                # blocks
                insts.pop()
                insts.extend(blocks.pop(target))
                # CFG
                common_join_cfg(bb, target, fixFF)
                update(bb)
            elif target == bb:
                # bb -> bb
                # blocks
                insts.pop()
                blocks[bb] = [WhileStatement(1, insts)]
                # CFG
                succs[bb].remove(bb)
                preds[bb].remove(bb)
                update(bb)
            elif len(insts) == 1:
                # preds -> bb (single goto) -> target
                for pred in preds[bb]:
                    pred_term = blocks[pred][-1]
                    if not isinstance(pred_term, CondStatement):
                        raise RuntimeError("CondStatement in StructureReconstruction(preds -> bb (single goto) -> target) temporary not supported...")
                    assert not calls[bb]
                    # blocks
                    p_target = pred_term.target
                    p_fall = pred_term.fall
                    if p_target == bb:
                        pred_term.target = target
                    if p_fall == bb:
                        pred_term.fall = target
                  # print(p_target, p_fall, bb, target)
                    # CFG
                    succs[pred].discard(bb)
                    succs[pred].add(target)
                    queue.append(pred)
                preds[target].remove(bb)
                preds[target].extend(preds[bb])
                update(bb)
                del blocks[bb], preds[bb], succs[bb], calls[bb]
                check_cfg(FF)
    check_cfg(FF)


def call_blocks(insts):
    result = set()
    for inst in insts:
        if isinstance(inst.expr, CallExpression):
            result.add(inst.expr.goto)
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
    print("\n|cycles|:", len(cycles))
    for cycle in cycles:
        all_calls = set()
        for bb in cycle:
            all_calls |= calls[bb]
        print(all_calls, "->", print_colored_set(cycle, blocks, calls))
        for bb in cycle:
            term_inst = blocks[bb][-1]
            if isinstance(term_inst, ReturnStatement):
                print(" ", term_inst)


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

    FF = make_cfg(blocks)
    dcm = check_users(FF)  # default_const_map
    get_cycles(FF)
    DF_LV = LiveVariables(FF)
    ConstantPropogationAndFolding(FF, DF_LV, dcm)
    ForwardSubstitution(FF, DF_LV)
    MethodCallDeapply(FF)
    StructureReconstruction(FF)
  # DF_LV = LiveVariables(FF)
    print_cfg(FF) #, DF_LV)


def main():
    gotos = stage1()
    stage2(gotos)


if __name__ == "__main__":
    main()
