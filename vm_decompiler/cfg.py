from io import StringIO
from collections import deque

from .ir import _regbase, _name2reg, Undefined, Null
from .ir import RegArray, CallExpression
from .ir import AssignStatement, ReturnStatement, GotoStatement, CondStatement, JumpStatement


SKIP_BLOCKS_WITH_CFG = True


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

def call_blocks(insts):
    result = set()
    for inst in insts:
        if isinstance(inst.expr, CallExpression):
            result.add(inst.expr.goto)
    return result


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


# ~~~ helpers ~~~

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


# ~~~ dataflow analysis ~~~

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
