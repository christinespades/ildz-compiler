from ast import *

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def consume(self, type_=None):
        token = self.tokens[self.pos]
        if type_ and token.type != type_:
            raise Exception(f"Expected {type_}, got {token.type}")
        self.pos += 1
        return token

    def parse(self):
        statements = []
        while self.pos < len(self.tokens):
            statements.append(self.statement())
        return Program(statements)

    def statement(self):
        tok = self.peek()

        if tok.type == "IDENT":
            return self.assignment()
        if tok.type == "FUNC":
            return self.function_def()
        if tok.type == "IF":
            return self.if_stmt()
        if tok.type == "WHILE":
            return self.while_stmt()
        if tok.type == "PRINT":
            return self.print_stmt()
        if tok.type == "READ":
            return self.read_stmt()
        if tok.type == "RETURN":
            return self.return_stmt()
        if tok.type == "WRITE":
            return self.write_stmt()

        return self.expr()

    def assignment(self):
        name = self.consume("IDENT").value
        self.consume("EQUAL")
        value = self.expr()
        return Assignment(name, value)

    def function_def(self):
        self.consume("FUNC")
        name = self.consume("IDENT").value

        params = []
        if self.peek().type == "IDENT":
            params.append(self.consume("IDENT").value)
            while self.peek().type == "COMMA":
                self.consume("COMMA")
                params.append(self.consume("IDENT").value)

        self.consume("NEWLINE")
        self.consume("INDENT")

        body = []
        while self.peek().type != "DEDENT":
            body.append(self.statement())

        self.consume("DEDENT")
        return FunctionDef(name, params, body)

    def if_stmt(self):
        self.consume("IF")
        condition = self.expr()

        self.consume("NEWLINE")
        self.consume("INDENT")

        body = []
        while self.peek().type != "DEDENT":
            body.append(self.statement())

        self.consume("DEDENT")

        # ELSE = second indent block immediately after
        else_body = []
        if self.peek().type == "INDENT":
            self.consume("INDENT")
            while self.peek().type != "DEDENT":
                else_body.append(self.statement())
            self.consume("DEDENT")

        return If(condition, body, else_body)

    def while_stmt(self):
        self.consume("WHILE")
        condition = self.expr()

        self.consume("NEWLINE")
        self.consume("INDENT")

        body = []
        while self.peek().type != "DEDENT":
            body.append(self.statement())

        self.consume("DEDENT")
        return While(condition, body)

    def print_stmt(self):
        self.consume("PRINT")
        return Print(self.expr())

    def read_stmt(self):
        self.consume("READ")
        return Return(self.expr())

    def return_stmt(self):
        self.consume("RETURN")
        return Return(self.expr())

    def write_stmt(self):
        self.consume("WRITE")
        return Return(self.expr())

    def expr(self):
        left = self.primary()

        while self.peek().type in ("EQUAL", "LT"):
            op = self.consume().type
            right = self.primary()
            left = BinaryOp(left, op, right)

        return left

    def primary(self):
        tok = self.peek()

        if tok.type == "NUMBER":
            return Literal(self.consume().value)

        if tok.type == "CALL":
            self.consume()
            name = self.consume("IDENT").value
            args = []

            if self.peek().type not in ("NEWLINE", "DEDENT"):
                args.append(self.expr())
                while self.peek().type == "COMMA":
                    self.consume()
                    args.append(self.expr())

            return FunctionCall(name, args)

        if tok.type == "IDENT":
            val = self.consume().value

            # string rule: starts with letter → treat as string
            if not val[0].isdigit():
                return Literal(val)

            return Identifier(val)

        raise Exception(f"Unexpected token {tok}")