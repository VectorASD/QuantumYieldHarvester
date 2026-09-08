from io import StringIO


class Undefined:
    def __repr__(self):
        return "undefined"
class Null:
    def __repr__(self):
        return "null"

type Const = str | int | float | bool

INDENT = "  "


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

def Caesar(shift, right, left):
    eval = (left + right).strip()
    assert eval[0] == '[' and eval[-1] == ']'
    return ''.join(chr(int(part) - shift) for part in eval[1:-1].split(',') if part.strip())

def check_Caesar():
    print("~~~ check_Caesar ~~~")
    decrypted = Caesar(8, '5,]', '[10')
    print(decrypted)
    assert decrypted == 'a'
    decrypted = Caesar(7, '105,53,119,124,122,111,47,104,53,106,111,104,121,74,118,107,108,72,123,47,112,48,48,66,121,108,123,124,121,117,39,105,]', '[125,104,121,39,112,68,55,51,105,68,98,100,66,109,118,121,47,66,112,67,104,53,115,108,117,110,123,111,66,112,50,50,48,')
    print(decrypted)
    assert decrypted == 'var i=0,b=[];for(;i<a.length;i++)b.push(a.charCodeAt(i));return b'
    print()

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
        write(f"        call {self.goto!r} while !{_regbase[201]}\n")
        write(f"        return (delete {_regbase[201]})\n")
        write("      }")
        return buffer.getvalue()
    def __repr__(self):
        if self.args:
            return f"lambda *a: call {self.goto!r} ({self.args} = a)"
        return f"lambda: call {self.goto!r} ()"
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
        return f"call {self.goto!r} ({args})"
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
        return f"{pad}goto {self.target!r}"
    def replace_bb(self, what, to):
        if self.target == what:
            self.target = to

class CondStatement(Statement):
    def __init__(self, target, condition: Expression|Const, fall):
        self.target = target
        self.cond = condition
        self.fall = fall
    def __repr__(self, pad=""):
        return f"{pad}goto {self.target!r} if {self.cond} else {self.fall!r}"
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
    def replace_bb(self, what, to):
        if self.target == what:
            self.target = to
        if self.fall == what:
            self.fall = to

JumpStatement = GotoStatement | CondStatement
TermStatement = JumpStatement | ReturnStatement | HaltStatement


class IfStatement(Statement):
    def __init__(self, condition: Expression|Const, then_stmts: list[Statement], else_stmts: list[Statement]|None = None):
        self.cond = condition
        self.then_stmts = then_stmts
        self.else_stmts = else_stmts or ()
    def __repr__(self, pad=""):
        next_pad = pad + INDENT
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
        next_pad = pad + INDENT
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
        next_pad = pad + INDENT
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
    print("~~~ check_printers ~~~")
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


if __name__ == "__main__":
    check_Caesar()
    check_printers()
