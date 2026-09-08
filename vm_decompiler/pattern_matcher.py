if __name__ == "__main__":
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from vm_decompiler.pattern_matcher import main
    main(); exit()


import re
from array import array

from .ir import CondStatement, GotoStatement, HaltStatement
from .cfg import Block, make_cfg


TOKEN_UNKNOWN = 0
TOKEN_NAME = 1
TOKEN_NUMBER = 2
TOKEN_PUNCT = 2

PUNCTUATION = "{}!"

class Parser:
    findall_tokens = re.compile(rf"[A-Za-z_]+|\d+|[{re.escape(PUNCTUATION)}]").findall

    lexer = array('B', bytes((TOKEN_UNKNOWN,)) * 256)  # ascii
    for letter in range(ord('A'), ord('Z') + 1): lexer[letter] = TOKEN_NAME
    for letter in range(ord('a'), ord('z') + 1): lexer[letter] = TOKEN_NAME
    lexer[ord('_')] = TOKEN_NAME
    for letter in range(ord('0'), ord('9') + 1): lexer[letter] = TOKEN_NUMBER
    for letter in PUNCTUATION:
        lexer[ord(letter)] = TOKEN_PUNCT

    def __init__(self, grammer: str):
        lexer = Parser.lexer
        self.tokens: list[tuple[int, str]] = \
            [(lexer[ord(token[0])], token) for token in Parser.findall_tokens(grammer)]
        self.pos = 0

    def eos(self):
        return self.pos >= len(self.tokens)

    def peek(self, shift=0):
        pos, tokens = self.pos, self.tokens
        if pos < len(tokens):
            self.pos = pos + shift
            return tokens[pos]
        return (TOKEN_UNKNOWN, '')

    def match(self, type: int|str, value: str|None = None):
        _type, tok = self.peek()
        if value is None:
            if isinstance(type, int):
                if _type == type:
                    self.pos += 1
                    return tok
            elif isinstance(type, str):
                if tok == type:
                    self.pos += 1
                    return True
        if _type == type or tok == value:
            self.pos += 1
            return True
        return False

    def expect(self, type: int|str, value: str|None = None):
        matched = self.match(type, value)
        if not matched:
            _type, tok = self.peek(0)
            pair = f"{type!r}" if value is None else f"({type!r}, {value!r})"
            raise ValueError(f"Expected {pair}, but finded ({_type!r}, {tok!r})")
        return matched


def print_sep(title: str|None = None):
    print()
    if title:
        size = 100 - (len(title) + 2)
        print('-' * (size//2), title, '-' * (size - size//2))
    else:
        print('-' * 100)
    print()


def generate_pattern(grammar: str):
    parser = Parser(grammar)

    blocks = {}
    current_block = add = None
    def on_block(bb: Block):
        nonlocal current_block, add
        current_block = bb
        add = bb.insts.append
    def new_block() -> Block:
        bb = Block(len(blocks))
        blocks[bb] = bb.insts
        return bb
    on_block(new_block())

    def visit_if():
        yeah, nop = new_block(), new_block()
        inv = parser.match('!')
        parser.expect('{')
        add(CondStatement(nop, "cond", yeah) if inv else CondStatement(yeah, "cond", nop))

        on_block(yeah)
        visit_statement()  # '}'

        add(GotoStatement(nop))
        on_block(nop)

    def visit_statement():
        while not parser.eos():
            if parser.match("if"):
                visit_if()
            elif parser.match('}'):
                return
            else:
                raise ValueError(f"Unknown instruction: {parser.peek()}")

    print_sep(grammar)
    visit_statement()
    add(HaltStatement())

    CFG = make_cfg(blocks)
    print(CFG)


def main():
    generate_pattern("if {}")
    generate_pattern("if! {}")
    generate_pattern("if {if! {} if {}}")
    print_sep()
