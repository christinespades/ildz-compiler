from lexer import Lexer
from parser import Parser
from codegen import Codegen

with open("input.ildz") as f:
    source = f.read()

lexer = Lexer(source)
tokens = lexer.tokenize()

parser = Parser(tokens)
ast = parser.parse()

codegen = Codegen()
output = codegen.generate(ast)

with open("out.txt", "w") as f:
    f.write(output)