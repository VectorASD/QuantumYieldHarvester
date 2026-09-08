from __future__ import annotations

from io import StringIO
from collections import deque, defaultdict
from typing import Iterable

from .ir import _regbase, _name2reg, Undefined, Null, INDENT
from .ir import RegArray, CallExpression
from .ir import Statement, AssignStatement, ReturnStatement, GotoStatement, CondStatement, JumpStatement, TermStatement


SKIP_FUNC_BLOCKS_IN_CFG = True


RED    = "\33[91m"
GREEN  = "\33[92m"
YELLOW = "\33[93m"
RESET  = "\33[0m"

class Block:
    def __init__(self, id: int, cfg: CFG|None = None):
        self.id = id
        self.insts: list[Statement] = []
        self.deleted = False
        self.cfg = cfg

    def __repr__(self, colored=False):
        tag = f"BB{self.id}"
        if colored:
            color = self.get_color()
            if color is not None:
                tag = f"{color}{tag}{RESET}"
        return tag

    def __str__(self, pad = "", misc: Iterable[str] = ()):
        buffer = StringIO()
        write = buffer.write
        write(f"{pad}~~~ {self!r}{''.join(misc)}")
        pad += INDENT
        if self.deleted:
            write(f"\n{pad}DELETED")
        else:
            for inst in self.insts:
                write(f"\n{inst.__repr__(pad=pad)}")
        return buffer.getvalue()

    def __eq__(self, right):
        return isinstance(right, Block) and self.id == right.id
    def __hash__(self):
        return hash(self.id)

    def __lt__(self, right):
        if isinstance(right, Block):
            return self.id < right.id
        return NotImplemented

    def clean_insts(self):
        insts = self.insts
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

    def get_color(self):
        cfg = self.cfg
        if cfg is not None:
            _input = bool(cfg.calls[self])
            output = bool(cfg.call_dsts[self])
            color = YELLOW if _input and output else GREEN if _input else RED if output else None
            return color


class CFG:
    def __init__(self):
        self.blocks:    dict[Block, list[Statement]] = {}
        self.preds:     dict[Block, list[Block]] = defaultdict(list)
        self.call_dsts: dict[Block, list[Block]] = {}
        self.succs:     dict[Block, set[Block]] = {}
        self.calls:     dict[Block, set[Block]] = defaultdict(set)
        self.FF = self.blocks, self.preds, self.succs, self.calls, self.call_dsts
        self.DF_LV = None
        self.default_const_map = None

    def __str__(self):
        blocks, preds, succs, calls, call_dsts = self.FF
        DF_LV = self.DF_LV
        if DF_LV is not None:
            GEN, KILL, IN, OUT = DF_LV
        buffer = StringIO()
        write = buffer.write
        first = True
        for bb in blocks:
            if SKIP_FUNC_BLOCKS_IN_CFG and not preds[bb] and not succs[bb]:
                continue
            if first:
                first = False
            else:
                write("\n\n")
            if DF_LV is not None:
              # write(f"GEN: {mask2regs(GEN[bb])}\n")
              # write(f"KILL: {mask2regs(KILL[bb])}\n")
                write(f"IN: {mask2regs(IN[bb])}\n")
                write(f"OUT: {mask2regs(OUT[bb])}\n")
            misc = (
                f"  // preds: {preds[bb]}" if preds[bb] else '',
                f"  // calls: {calls[bb]}" if calls[bb] else ''
            )
            write(bb.__str__(misc=misc))
        return buffer.getvalue()

    def has_term(self, bb: Block):
        insts = bb.insts
        return insts and isinstance(insts[-1], TermStatement)

    def add_term(self, bb: Block, term: TermStatement):
        if self.has_term(bb):
            raise RuntimeError(f"Cannot add terminator to a basic block ({bb!r}) that already has a terminator")
        bb.insts.append(term)

        preds, succs = self.preds, self.succs
        if isinstance(term, JumpStatement):
            succs[bb].add(term.target)
            preds[term.target].append(bb)
            if isinstance(term, CondStatement):
                succs[bb].add(term.fall)
                preds[term.fall].append(bb)
        else:
            raise RuntimeError(f"add_term: unsupported {type(term).__name__!r}")

    def delete_term(self, bb: Block, *, save_term: bool = False) -> JumpStatement:
        if not self.has_term(bb):
            raise RuntimeError(f"Cannot delete terminator from a basic block ({bb!r}) that has no terminator")
        term = bb.insts[-1] if save_term else bb.insts.pop()
        preds, succs = self.preds, self.succs
        if isinstance(term, JumpStatement):
            succs[bb].remove(term.target)
            preds[term.target].remove(bb)
            if isinstance(term, CondStatement):
                succs[bb].remove(term.fall)
                preds[term.fall].remove(bb)
        elif not save_term:
            raise RuntimeError(f"delete_term: unsupported {type(term).__name__!r}")
        return term

    def replace_term(self, bb: Block, term: TermStatement):
        self.delete_term(bb)
        self.add_term(bb, term)


    def extend_block(self, bb: str, insts: Iterable[Statement]|Statement):
        if self.has_term(bb):
            raise RuntimeError("Cannot add instructions to a basic block that already has a terminator")

        calls, call_dsts = self.calls, self.call_dsts
        def call_traverse(node):
            calls[node.goto].add(bb)
            call_dsts[bb].append(node.goto)
        traverse = {call_type: call_traverse for call_type in CallExpression.__args__}.get

        if isinstance(insts, Statement):
            insts = (insts,)

        add_inst = bb.insts.append
        it = iter(insts)
        for inst in it:
            if isinstance(inst, JumpStatement):
                self.add_term(bb, inst)
                if tuple(it):
                    raise RuntimeError("Encountered terminator not at the end of 'insts'")
            else:
                add_inst(inst)
                inst.traverse(traverse)

    def add_block(self, block: Block):
        blocks, _, succs, _, call_dsts = self.FF
        block.insts, insts = [], block.insts
        block.cfg = self
        blocks[block] = block.insts  # add with save order
        succs[block] = set()
        call_dsts[block] = []
        self.extend_block(block, insts)

    def delete_block(self, bb: Block, *, save_term: bool = False, check_preds = True):
        blocks, preds, succs, calls, call_dsts = self.FF
        if (check_preds and preds[bb]) or calls[bb]:
            raise RuntimeError(f"can't delete this {bb!r}: preds={preds[bb]}, calls={calls[bb]}")
        if self.has_term(bb):
            self.delete_term(bb, save_term=save_term)
        if succs[bb]:
            raise RuntimeError(f"Removing terminator don't release of {bb!r}: succs={succs[bb]}")
        for goto in call_dsts[bb].copy():
            calls[goto].discard(bb)
            call_dsts[bb].remove(goto)
        del blocks[bb], succs[bb], calls[bb], call_dsts[bb]
        if check_preds:
            del preds[bb]
        bb.deleted = True
        return bb.insts


    # ~~~ helpers ~~~

    def check_users(self):
        blocks = self.blocks
        users = set(); add = users.add
        for insts in blocks.values():
            for inst in insts:
                if isinstance(inst, AssignStatement):
                    add(inst.reg)
        const_regs = set(str(reg) for reg in _regbase if reg not in users)
        defaults = {"c0": 0, "c1": 1, "(void 0)": Undefined(), "null": Null()}
        dcm = {_name2reg[k]: v for k, v in defaults.items() if k in const_regs}
        print("\nconst regs:", const_regs)
        print("default const map:", dcm)
        for insts in blocks.values():
            term_inst = insts[-1]
            if isinstance(term_inst, ReturnStatement):
                term_inst.dcm = dcm
        self.default_const_map = dcm

    def get_cycles(self):
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

        blocks, preds, succs, calls, call_dsts = self.FF
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
            print(all_calls, "->", print_colored_set(cycle))
            for bb in cycle:
                term_inst = bb.insts[-1]
                if isinstance(term_inst, ReturnStatement):
                    print(" ", term_inst)
        print()

    def check(self):
        blocks, old_preds, old_succs, old_calls, old_call_dsts = self.FF
        _, preds, succs, calls, call_dsts = make_cfg(blocks).FF
        errors = []
        for bb in blocks:
            if sorted(old_preds[bb]) != sorted(preds[bb]):
                errors.append(f"preds[{bb!r}]:\n    actual: {old_preds[bb]}\n    expected: {preds[bb]}")
            if old_succs[bb] != succs[bb]:
                errors.append(f"succs[{bb!r}]:\n    actual: {old_succs[bb]}\n    expected: {succs[bb]}")
            if old_calls[bb] != calls[bb]:
                errors.append(f"calls[{bb!r}]:\n    actual: {old_calls[bb]}\n    expected: {calls[bb]}")
          # TODO:
          # if sorted(old_call_dsts[bb]) != sorted(call_dsts[bb]):
          #     errors.append(f"call_dsts[{bb!r}]:\n    actual: {old_call_dsts[bb]}\n    expected: {call_dsts[bb]}")
        if errors:
            print(*errors, sep='\n')
            exit()


    # ~~~ dataflow analysis ~~~

    def LiveVariables(self):
        blocks, succs = self.blocks, self.succs
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

        self.DF_LV = GEN, KILL, IN, OUT


def make_cfg(blocks: Iterable[Block]):
    cfg = CFG()
    for block in blocks:
        cfg.add_block(block)
    return cfg


# ~~~ helpers ~~~

def print_colored_set(_set: set[Block]):
    buffer = StringIO()
    write = buffer.write
    write('{')
    write(", ".join(bb.__repr__(colored=True) for bb in _set))
    write('}')
    return buffer.getvalue()

_id2shift = tuple(1 << i for i in range(256))
def mask2regs(mask):
    return RegArray(_regbase[i] for i, shift in enumerate(_id2shift) if mask & shift)
