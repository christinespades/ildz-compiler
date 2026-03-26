import re

class Token:
    def __init__(self, type_, value=None):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"{self.type}:{self.value}"


class Lexer:
    def __init__(self, text):
        self.lines = text.splitlines()
        self.tokens = []
        self.indent_stack = [0]

    def tokenize(self):
        for line in self.lines:
            self._process_line(line)

        while len(self.indent_stack) > 1:
            self.tokens.append(Token("DEDENT"))
            self.indent_stack.pop()

        return self.tokens

    def _process_line(self, line):
        # strip comments
        if "|" in line:
            line = line.split("|", 1)[0]

        if not line.strip():
            return

        indent = len(line) - len(line.lstrip(" "))

        if indent > self.indent_stack[-1]:
            self.indent_stack.append(indent)
            self.tokens.append(Token("INDENT"))
        while indent < self.indent_stack[-1]:
            self.indent_stack.pop()
            self.tokens.append(Token("DEDENT"))

        self._tokenize_code(line.strip())
        self.tokens.append(Token("NEWLINE"))

    def _tokenize_code(self, line):
        parts = re.findall(r"\.\.|\.|=|<|,|\S+", line)

        for part in parts:
            if part == "..":
                self.tokens.append(Token("CALL"))
            elif part == ".":
                self.tokens.append(Token("FUNC"))
            elif part == "=":
                self.tokens.append(Token("EQUAL"))
            elif part == "<":
                self.tokens.append(Token("LT"))
            elif part == ",":
                self.tokens.append(Token("COMMA"))
            elif part == "if":
                self.tokens.append(Token("IF"))
            elif part == "fr":
                self.tokens.append(Token("WHILE"))
            elif part == "pr":
                self.tokens.append(Token("PRINT"))
            elif part == "ret":
                self.tokens.append(Token("RETURN"))
            elif re.match(r"^\d+(\.\d+)?$", part):
                self.tokens.append(Token("NUMBER", part))
            else:
                self.tokens.append(Token("IDENT", part))