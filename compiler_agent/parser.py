from .lexer import Token, TokenType
from .ast_nodes import ActionNode, ConditionNode, IfNode, ProgramNode, RepeatNode

TARGET_STOPWORDS = {
    "it", "them", "this", "that", "there", "screenshot", "screen", "text", "image",
    "picture", "selection", "clipboard", "file", "new", "app", "application",
    "program", "window", "key", "keys", "button",
}


class ParserError(Exception):
    pass


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.action_count = 0

    def peek(self, offset=0) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def expect(self, type_: TokenType) -> Token:
        tok = self.peek()
        if tok.type != type_:
            raise ParserError(
                f"Expected {type_.name} but got {tok.type.name} "
                f"('{tok.text or tok.value}') at character {tok.pos}"
            )
        return self.advance()

    def is_kw(self, tok, *names):
        return tok.type == TokenType.KEYWORD and tok.value in names

    def starts_statement(self, tok):
        return tok.type == TokenType.VERB or self.is_kw(tok, "IF", "REPEAT")

    def parse(self) -> ProgramNode:
        if self.peek().type == TokenType.EOF:
            raise ParserError("Empty command")
        statements = self.parse_block()
        tok = self.peek()
        if tok.type != TokenType.EOF:
            if self.is_kw(tok, "ELSE"):
                raise ParserError(f"'otherwise' at character {tok.pos} has no matching 'if'")
            if self.is_kw(tok, "END"):
                raise ParserError(f"'end' at character {tok.pos} has nothing to close")
            raise ParserError(
                f"Unexpected '{tok.text or tok.value}' at character {tok.pos}: "
                f"expected 'and', 'then' or the end of the command"
            )
        return ProgramNode(statements=statements)

    def parse_block(self):
        statements = [self.parse_statement()]
        while True:
            tok = self.peek()
            if tok.type == TokenType.CONNECTOR:
                nxt = self.peek(1)
                if nxt.type == TokenType.EOF or self.is_kw(nxt, "ELSE", "END"):
                    self.advance()
                    break
                self.advance()
                statements.append(self.parse_statement())
            elif self.starts_statement(tok):
                statements.append(self.parse_statement())
            else:
                break
        return statements

    def parse_statement(self):
        tok = self.peek()
        if self.is_kw(tok, "IF"):
            return self.parse_if()
        if self.is_kw(tok, "REPEAT"):
            return self.parse_repeat()
        if tok.type != TokenType.VERB:
            shown = tok.text or tok.value or "end of command"
            raise ParserError(
                f"Expected a command word (open, type, paste, ...) but got "
                f"'{shown}' at character {tok.pos}"
            )
        action = self.parse_action()
        if self.peek().type == TokenType.NUMBER and self.is_kw(self.peek(1), "TIMES"):
            count = self.advance().value
            self.advance()
            return RepeatNode(count=count, body=[action])
        return action

    def parse_if(self):
        self.advance()
        condition = self.parse_condition()
        if self.peek().type == TokenType.CONNECTOR:
            self.advance()
        then_body = self.parse_block()
        else_body = []
        if self.is_kw(self.peek(), "ELSE"):
            self.advance()
            if self.peek().type == TokenType.CONNECTOR:
                self.advance()
            else_body = self.parse_block()
        self.parse_end("IF")
        return IfNode(condition=condition, then_body=then_body, else_body=else_body)

    def parse_repeat(self):
        self.advance()
        tok = self.peek()
        if tok.type != TokenType.NUMBER:
            raise ParserError(f"'repeat' must be followed by a count, e.g. 'repeat 3 times' (character {tok.pos})")
        count = self.advance().value
        if self.is_kw(self.peek(), "TIMES"):
            self.advance()
        if self.peek().type == TokenType.CONNECTOR:
            self.advance()
        body = self.parse_block()
        self.parse_end("REPEAT")
        return RepeatNode(count=count, body=body)

    def parse_end(self, kind):
        if self.is_kw(self.peek(), "END"):
            self.advance()
            if self.is_kw(self.peek(), kind):
                self.advance()

    def parse_condition(self):
        words = []
        while True:
            tok = self.peek()
            if tok.type in (TokenType.IDENTIFIER, TokenType.STRING):
                self.advance()
                if tok.type == TokenType.STRING or tok.value.lower() not in TARGET_STOPWORDS:
                    words.append(str(tok.value))
            elif tok.type == TokenType.PREP:
                self.advance()
            else:
                break
        if not words:
            tok = self.peek()
            raise ParserError(f"'if' needs something to check, e.g. 'if notes.txt exists' (character {tok.pos})")
        subject = " ".join(words)
        negated = False
        if self.is_kw(self.peek(), "IS"):
            self.advance()
        if self.is_kw(self.peek(), "NOT"):
            self.advance()
            negated = True
        tok = self.peek()
        if self.is_kw(tok, "EXISTS"):
            self.advance()
            return ConditionNode("EXISTS", subject, negated)
        if self.is_kw(tok, "MISSING"):
            self.advance()
            return ConditionNode("EXISTS", subject, not negated)
        if self.is_kw(tok, "RUNNING") or (tok.type == TokenType.VERB and tok.value == "OPEN_APP"):
            self.advance()
            return ConditionNode("RUNNING", subject, negated)
        raise ParserError(
            f"Unknown condition after '{subject}' at character {tok.pos}: "
            f"use 'exists', 'does not exist', 'is running' or 'is open'"
        )

    def parse_action(self) -> ActionNode:
        verb_tok = self.expect(TokenType.VERB)
        self.action_count += 1
        node = ActionNode(verb=verb_tok.value, word=(verb_tok.text or "").lower(), index=self.action_count)
        target_words = []
        while True:
            tok = self.peek()
            if tok.type == TokenType.VERB:
                if tok.value == node.verb:
                    self.advance()
                    continue
                break
            if tok.type == TokenType.NUMBER:
                if self.is_kw(self.peek(1), "TIMES"):
                    break
                self.advance()
                node.args.setdefault("number", tok.value)
                continue
            if tok.type == TokenType.STRING:
                self.advance()
                node.args.setdefault("text", tok.value)
                continue
            if tok.type == TokenType.PREP:
                self.advance()
                continue
            if tok.type == TokenType.IDENTIFIER:
                self.advance()
                if node.verb == "OPEN_APP" and tok.value.lower() in ("new", "another", "fresh"):
                    node.args["new"] = True
                    continue
                keep = node.verb == "PRESS" or (node.verb == "CREATE_FILE" and tok.value.lower() == "text")
                if keep or tok.value.lower() not in TARGET_STOPWORDS:
                    target_words.append(tok.value)
                continue
            break
        if target_words:
            node.target = " ".join(target_words)
        return node
