from collections import deque, defaultdict
from pathlib import Path
from io import StringIO

from .ir import Reg, _regbase, _name2reg, Undefined, Null
from .ir import Expression, RegIndex, RegArray, RegCall, CallExpression, InverseReg
from .ir import AssignStatement, HaltStatement, ReturnStatement, GotoStatement, CondStatement, JumpStatement
from .ir import IfStatement, WhileStatement, DoWhileStatement

from .ir_loader import parse_bytecode


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


class Pattern:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return f"Pattern({self.name!r})"
matcher_tree = {
    "cond": {
        (None, None): (
            1, 2, 1, None, {
                # 0 -> 1 -> 2
                #  \       ^
                #   \-----/
                "goto": {
                    2: (None, None, {1: (0,), 2: (0, 1)}, Pattern("if {}")),  # 37 matches
                },
                'x': (2, {
                    # 0 -> 2 -> 1
                    #  \       ^
                    #   \-----/
                    "goto": {
                        1: (None, None, {2: (0,), 1: (0, 2)}, Pattern("if !{}")),  # 13 matches
                    }
                }),
            }
        )
    }
}
def match_bb(FF, bb):
    blocks, preds, succs, calls = FF
    node = matcher_tree
    check_bb = bb

    bb2id = {bb: 0}
    id2bb = {0: bb}
    default_stack = []

    def check_defaults():
        nonlocal check_bb, node
        if default_stack:
            check_bb, node = default_stack.pop()
            assert check_bb in id2bb
            check_bb = id2bb[check_bb]
            return True
        return False

    def check_preds(preds_tree):
        for bb_id, preds_ids in preds_tree.items():
            bb = id2bb[bb_id]
            bb_preds = preds[bb]
            if sorted(bb_preds) != sorted(id2bb[id] for id in preds_ids):
                return True  # use defaults
        return False

    while True:
        term = blocks[check_bb][-1]
        term_kind = ("cond" if isinstance(term, CondStatement) else
                     "goto" if isinstance(term, GotoStatement) else
                     "return" if isinstance(term, ReturnStatement | HaltStatement) else
                     None)
        if term_kind is None:
            raise RuntimeError(f"Is not terminator: {type(term).__name__}, op: {term}")

        branch = node.get(term_kind)
        default = node.get('x')
        if default is not None:
            default_stack.append(default)

        if branch is None:
            if check_defaults():
                continue
            print("unknown branch")
            break
        if isinstance(term, CondStatement):
            check = bb2id.get(term.target), bb2id.get(term.fall)
        elif isinstance(term, GotoStatement):
            check = bb2id.get(term.target)
        else:
            1/0
        sign = branch.get(check)
        if sign is None:
            if check_defaults():
                continue
            print("unknown sign")
            break

        if isinstance(term, CondStatement):
            target_id, fall_id, check_bb, preds_tree, node = sign
            if target_id is not None:
                bb2id[term.target] = target_id
                id2bb[target_id] = term.target
            if fall_id is not None:
                bb2id[term.fall] = fall_id
                id2bb[fall_id] = term.fall
        elif isinstance(term, GotoStatement):
            target_id, check_bb, preds_tree, node = sign
            if target_id is not None:
                bb2id[term.target] = target_id
                id2bb[target_id] = term.target
        else:
            1/0

        if check_bb is not None:
            check_bb = id2bb[check_bb]
        if preds_tree is not None and check_preds(preds_tree):
            print("checking error")
            if check_defaults():
                continue
            break

        if isinstance(node, Pattern):
            print("finded:", node, bb2id)
            return node

def StructureReconstruction_v2(FF):  # CFG2AST  # CFG2AST
    blocks, preds, succs, calls = FF

    queue = deque(blocks)
    while queue:
        bb = queue.popleft()
        try: insts = blocks[bb]
        except KeyError: continue
        if not succs[bb]:
            continue
        print('.' * 100)
        print(bb2str(bb, insts))
        match_bb(FF, bb)
    exit()


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
    print()


def main():
    bytecode_path = Path(__file__).resolve().parent.parent / "webdriver" / "polygon" / "challenge2.js"
    blocks = parse_bytecode(bytecode_path)

    FF = make_cfg(blocks)
    dcm = check_users(FF)  # default_const_map
    get_cycles(FF)
    DF_LV = LiveVariables(FF)
    ConstantPropogationAndFolding(FF, DF_LV, dcm)
    ForwardSubstitution(FF, DF_LV)
    MethodCallDeapply(FF)
    StructureReconstruction_v2(FF)
  # DF_LV = LiveVariables(FF)
    print_cfg(FF) #, DF_LV)


if __name__ == "__main__":
    main()
