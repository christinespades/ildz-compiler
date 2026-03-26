class Codegen:
    def __init__(self):
        self.output = []

    def generate(self, node):
        self.visit(node)
        return "\n".join(self.output)

    def visit(self, node):
        method = f"visit_{type(node).__name__}"
        return getattr(self, method)(node)

    def visit_Program(self, node):
        for stmt in node.statements:
            self.visit(stmt)

    def visit_Assignment(self, node):
        self.output.append(f"SET {node.name}")

    def visit_Print(self, node):
        self.output.append("PRINT")

    def visit_FunctionDef(self, node):
        self.output.append(f"FUNC {node.name}")

    def visit_If(self, node):
        self.output.append("IF")

    def visit_While(self, node):
        self.output.append("WHILE")

    def visit_FunctionCall(self, node):
        self.output.append(f"CALL {node.name}")

    def visit_Return(self, node):
        self.output.append("RET")