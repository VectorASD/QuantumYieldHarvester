if __name__ == "__main__":
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from vm_decompiler.main import main
    main()
    exit()
    

from collections import deque, defaultdict
from pathlib import Path

from .ir import Reg
from .ir import Expression, RegIndex, RegCall, InverseReg
from .ir import AssignStatement, HaltStatement, ReturnStatement, GotoStatement, CondStatement
from .ir import IfStatement, WhileStatement, DoWhileStatement

from .cfg import Block, CFG, make_cfg
from .cfg import _id2shift, mask2regs

from .ir_loader import parse_bytecode


def ConstantPropogationAndFolding(CFG):
    blocks = CFG.blocks
    OUT, dcm = CFG.DF_LV[3], CFG.default_const_map
    for bb, insts in blocks.items():
        out = OUT[bb]
        const_map = dcm.copy()
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
            bb.clean_insts()

def ForwardSubstitution(CFG):
    """Do not call a second time, otherwise we will with `100% probability` break the original execution order of instructions!"""
    blocks, OUT = CFG.blocks, CFG.DF_LV[3]
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
            bb.clean_insts()

def MethodCallDeapply(CFG):
    blocks = CFG.blocks
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

def StructureReconstruction(CFG: CFG):  # CFG2AST
    blocks, preds, succs, calls, _ = CFG.FF

    def update(bb, check=True):
        queue.extend(preds[bb])
        queue.append(bb)
        queue.extend(succs[bb])
        if check:
            CFG.check()  # TODO: delete it...

    def analyze(bb, id):
        if bb.id == id:
            print(bb)
            print(target)
            print(fall)
          # print(succs[target] == {bb}, set(preds[target]) == {bb}, set(preds[fall]) == {bb})

    def branch_checking(end_bb, debug=True):
        """
        Temporary solution that helped uncover a hidden trap:
        we do NOT necessarily have to attach the fall branch after IfStatement and WhileStatement!
        If preds prevents doing that, just use GotoStatement instead.
        Then the purpose of branch_checking disappears, ordinary Ifs can do the same!
        """
        end_preds = preds[end_bb]
        if len(end_preds) < 2:
            return False
        debug = len(end_preds) == 3

        term_bb = None
        for bb in end_preds:
            term = bb.insts[-1]
            if isinstance(term, GotoStatement):
                if term_bb is not None or term.target != end_bb:
                    return False
                term_bb = bb

        cond_chain = []
        bb = term_bb
        for i in range(len(end_preds) - 1):
            bb_preds = preds[bb]
            if len(bb_preds) != 1:
                return False
            prev_bb, bb = bb, bb_preds[0]
            term = bb.insts[-1]
            if not isinstance(term, CondStatement):
                return False
            target, fall = term.target, term.fall
            if target == prev_bb and fall == end_bb:
                cond_chain.append((bb, False))
            elif target == end_bb and fall == prev_bb:
                cond_chain.append((bb, True))
            else:
                return False

        if debug:
            print("checked:")
            for bb, inv in reversed(cond_chain):
                print(inv, bb)
            print(term_bb)
            print(end_bb)

        prev_bb = term_bb
        for bb, inv in cond_chain:
            then_body = CFG.delete_block(prev_bb, check_preds=False)
            prev_bb = bb
            cond = CFG.delete_term(bb).cond
            if inv:
                cond = InverseReg(cond)
            CFG.extend_block(bb, (IfStatement(cond, then_body),))
        fall_body = CFG.delete_block(end_bb, save_term=True)
        CFG.extend_block(bb, fall_body)
        if debug:
            print("\nJOINED:")
            print(bb)
            print("-" * 100)
            print()
        update(bb)
        return True

    queue = deque(blocks)
    while queue:
        bb: Block = queue.popleft()
        if bb.deleted:
            continue
        insts = bb.insts
        term_inst = insts[-1]
        if branch_checking(bb):
            pass
        elif isinstance(term_inst, CondStatement):
            target: Block = term_inst.target
            fall: Block = term_inst.fall
            if target == fall:
                raise RuntimeError("unchecked behavior")
            """
            if succs[target] == {fall} and set(preds[target]) == {bb} and set(preds[fall]) == {bb, target}:
                # bb -> target -> fall
                #   \            ^
                #    \----------/
                assert not calls[target] and not calls[fall]
                cond = CFG.delete_term(bb).cond
                then_body = CFG.delete_block(target)
                fall_body = CFG.delete_block(fall, save_term=True)
                CFG.extend_block(bb, (IfStatement(cond, then_body),))
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif succs[fall] == {target} and set(preds[fall]) == {bb} and set(preds[target]) == {bb, fall}:
                # bb -> fall -> target
                #   \          ^
                #    \--------/
                assert not calls[fall] and not calls[target]
                cond = CFG.delete_term(bb).cond
                then_body = CFG.delete_block(fall)
                fall_body = CFG.delete_block(target, save_term=True)
                CFG.extend_block(bb, (IfStatement(InverseReg(cond), then_body),))
                CFG.extend_block(bb, fall_body)
                update(bb)
            """
            if not succs[target] and set(preds[target]) == {bb} and set(preds[fall]) == {bb}:
                # bb -> target -> return
                #   \-> fall
                # bb;
                assert not calls[target] and not calls[fall]
                cond = CFG.delete_term(bb).cond
                then_body = CFG.delete_block(target, save_term=True)
                fall_body = CFG.delete_block(fall, save_term=True)
                CFG.extend_block(bb, (IfStatement(cond, then_body),))
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif not succs[fall] and set(preds[fall]) == {bb} and set(preds[target]) == {bb}:
                # bb -> fall -> return
                #   \-> target
                # bb;
                assert not calls[fall] and not calls[target]
                cond = CFG.delete_term(bb).cond
                then_body = CFG.delete_block(fall, save_term=True)
                fall_body = CFG.delete_block(target, save_term=True)
                CFG.extend_block(bb, (IfStatement(InverseReg(cond), then_body),))
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif succs[target] == {bb} and set(preds[target]) == {bb} and set(preds[fall]) == {bb}:
                #   /-> fall
                # bb -> target
                #  ^          \
                #   \---------/
                assert not calls[target] and not calls[fall]
                cond = CFG.delete_term(bb).cond
                do_body = CFG.delete_block(target)
                fall_body = CFG.delete_block(fall, save_term=True)
                insts.append(WhileStatement(cond, do_body.copy()))
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif succs[fall] == {bb} and set(preds[fall]) == {bb} and set(preds[target]) == {bb}:
                raise RuntimeError("unchecked!")
                #   /-> target
                # bb -> fall
                #  ^        \
                #   \-------/
                assert not calls[fall] and not calls[target]
                cond = CFG.delete_term(bb).cond
                do_body = CFG.delete_block(fall)
                fall_body = CFG.delete_block(target, save_term=True)
                insts.append(WhileStatement(cond, do_body.copy()))
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif target == bb and bb in preds[fall]:
                # bb -\-> fall
                #  ^  |
                #  \--/
                assert not calls[fall]
                cond = CFG.delete_term(bb).cond
                cycle = DoWhileStatement(cond, insts.copy())
                insts.clear()
                insts.append(cycle)
                if len(preds[fall]) == 1:
                    fall_body = CFG.delete_block(fall, save_term=True)
                    CFG.extend_block(bb, fall_body)
                else:
                    CFG.extend_block(bb, GotoStatement(fall))
                update(bb)
            elif fall == bb and set(preds[target]) == {bb}:
                # bb -\-> target
                #  ^  |
                #  \--/
                raise RuntimeError("unchecked!")
                assert not calls[target]
                cond = CFG.delete_term(bb).cond
                fall_body = CFG.delete_block(target, save_term=True)
                cycle = DoWhileStatement(cond, insts.copy())
                insts.clear()
                insts.append(cycle)
                CFG.extend_block(bb, fall_body)
                update(bb)
            elif len(insts) == 1:
                # preds -> bb (single cond) -> target
                #                          \-> fall
                term = insts[-1]
                for pred in preds[bb]:
                    pred_term = blocks[pred][-1]
                    if isinstance(pred_term, GotoStatement):
                        CFG.replace_term(pred, term)
                if not preds[bb] and not calls[bb]:
                    CFG.delete_block(bb)
                update(bb)
        elif isinstance(term_inst, GotoStatement):
            target = term_inst.target
            if target == bb:
                # bb -> bb
                assert not calls[target]
                CFG.delete_term(bb)
                cycle = WhileStatement(1, insts.copy())
                insts.clear()
                insts.append(cycle)
                update(bb)
            elif set(preds[target]) == {bb}:
                # bb -> target
                assert not calls[target]
                CFG.delete_term(bb)
                next_body = CFG.delete_block(target, save_term=True)
                CFG.extend_block(bb, next_body)
                update(bb)
            elif len(insts) == 1:
                # preds -> bb (single goto) -> target
                assert not calls[bb]
                queue.extend(preds[bb])
                queue.extend(succs[bb])
                for pred in preds[bb]:
                    pred_term = CFG.delete_term(pred)
                    pred_term.replace_bb(bb, target)
                    CFG.add_term(pred, pred_term)
                CFG.delete_block(bb)
                CFG.check()
    CFG.check()


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
        if bb.deleted:
            continue
        insts = bb.insts
        if not succs[bb]:
            continue
        print('.' * 100)
        print(bb)
        match_bb(FF, bb)
    exit()


def main():
    bytecode_path = Path(__file__).resolve().parent.parent / "webdriver" / "polygon" / "challenge2.js"
    blocks = parse_bytecode(bytecode_path)
  # print(*blocks, sep="\n\n")

    CFG = make_cfg(blocks)
    CFG.check_users()
    CFG.get_cycles()
    CFG.LiveVariables()
    ConstantPropogationAndFolding(CFG)
    ForwardSubstitution(CFG)
    MethodCallDeapply(CFG)
    StructureReconstruction(CFG)
  # StructureReconstruction_v2(CFG)
  # CFG.LiveVariables()
    CFG.DF_LV = None
    print(CFG)
    print("OK")
