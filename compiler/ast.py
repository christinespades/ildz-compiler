class Node:
    pass


class Program(Node):
    def __init__(self, statements):
        self.statements = statements


class Assignment(Node):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FunctionDef(Node):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body


class FunctionCall(Node):
    def __init__(self, name, args):
        self.name = name
        self.args = args


class If(Node):
    def __init__(self, condition, body, else_body):
        self.condition = condition
        self.body = body
        self.else_body = else_body


class While(Node):
    def __init__(self, condition, body):
        self.condition = condition
        self.body = body


class Print(Node):
    def __init__(self, value):
        self.value = value


class Return(Node):
    def __init__(self, value):
        self.value = value


class BinaryOp(Node):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class Literal(Node):
    def __init__(self, value):
        self.value = value


class Identifier(Node):
    def __init__(self, name):
        self.name = name