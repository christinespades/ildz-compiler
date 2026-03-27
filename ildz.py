# This file contains multiple versions of the compiler, or, more precisely, bits and pieces.. I need to clean this up!!!!

#!/usr/bin/env python3
# ildz.py — tiny bootstrap compiler: syntax -> C -> native exe -> run
# Works on Windows/macOS/Linux with clang/gcc/cl/tcc (first one found).

import os, sys, shlex, subprocess, tempfile, textwrap, pathlib

# ============================ LEXER ============================

KEYWORDS = {
    "pr", "if", "ret"
}

class Tok:
    def __init__(self, kind, val, pos, line, col):
        self.kind = kind
        self.val = val
        self.pos = pos
        self.line = line
        self.col = col
    def __repr__(self):
        return f"Tok({self.kind},{self.val})"

def lex(src):
    i, n = 0, len(src)
    line, col = 1, 1
    toks = []
    def peek(): return src[i] if i < n else ''
    def adv():
        nonlocal i, line, col
        ch = peek()
        i += 1
        if ch == '\n':
            line += 1
            col = 1
        else:
            col += 1
        return ch
    while i < n:
        c = peek()
        if c in ' \t\r':
            adv()
            continue
        if c == '\n':
            start_line, start_col = line, col
            adv()
            toks.append(Tok('NL', '\\n', i, start_line, start_col))
            continue
        if c == ';' and i+1<n and src[i+1]==';':
            i += 2; col += 2
            while i+1<n and src[i:i+2] != ';;':
                if src[i] == '\n':
                    line += 1
                    col = 1
                else:
                    col += 1
                i += 1
            if i+1<n and src[i:i+2] == ';;':
                i += 2; col += 2
            continue
        if c == ';':
            i += 1; col += 1
            while i<n and src[i] != '\n' and (i+1>=n or src[i:i+2] != ';;'):
                if src[i] == ';':
                    i += 1; col += 1
                    break
                i += 1; col += 1
            continue
        if c == '/' and i+1<n and src[i+1]=='/':
            while i<n and src[i] != '\n':
                i+=1
                col+=1
            continue
        if c.isalpha() or c=='_':
            j=i
            start_line, start_col = line, col
            while i<n and (src[i].isalnum() or src[i]=='_'):
                i+=1
                col+=1
            word = src[j:i]
            kind = 'KW' if word in KEYWORDS else 'ID'
            toks.append(Tok(kind, word, j, start_line, start_col))
            continue
        if c.isdigit():
            j=i
            start_line, start_col = line, col
            while i<n and src[i].isdigit():
                i+=1
                col+=1
            toks.append(Tok('INT', src[j:i], j, start_line, start_col))
            continue
        if c == '"':
            j = i+1
            start_line, start_col = line, col
            i += 1; col += 1
            buf=[]
            while i<n and src[i] != '"':
                if src[i] == '\\' and i+1<n:
                    esc = src[i+1]
                    buf.append({'n':'\n','t':'\t','r':'\r','"':'"','\\':'\\'}.get(esc, esc))
                    i += 2
                    col += 2
                else:
                    buf.append(src[i])
                    i+=1
                    col+=1
            if i>=n or src[i] != '"':
                raise SyntaxError(f"ildzc[lexer:{i}] error at {line}:{col}: Unclosed string")
            i += 1
            col += 1
            toks.append(Tok('STR',''.join(buf), j, start_line, start_col))
            continue
        if c in '{}(),=+-*/<>!:\'':
            start_line, start_col = line, col
            two = src[i:i+2]
            if two == "''":
                toks.append(Tok('SYM', "''", i, line, col))
                i += 2
                col += 2
                continue
            if two in ('==', '!=', '<=', '>='):
                toks.append(Tok('OP', two, i, line, col))
                i += 2
                col += 2
                continue
            if c == '=':  # Treat single '=' as equality operator
                toks.append(Tok('OP', '==', i, line, col))
                i += 1
                col += 1
                continue
            # For single char symbols like '<', '>', ':', etc.
            toks.append(Tok('SYM', c, i, line, col))
            i += 1
            col += 1
            continue
        raise SyntaxError(f"ildzc[lexer:{i}] error at {line}:{col}: Unexpected char {c!r}")
    toks.append(Tok('EOF','',n,line,col))
    return toks  # keep newlines for statement termination

# ============================ AST NODES ============================

class Node: pass
class Program(Node):
    def __init__(self, decls): self.decls = decls
class Fn(Node):
    def __init__(self, name, params, body, param_types=None):
        self.name = name
        self.params = params
        self.body = body
        self.param_types = param_types or ['int'] * len(params)  # Default to int if not specified
class Block(Node):
    def __init__(self, stmts): self.stmts = stmts
class Let(Node):
    def __init__(self, names, exprs, types=None):
        self.names = names
        self.exprs = exprs
        self.types = types or ['int'] * len(names)
class Return(Node):
    def __init__(self, expr): self.expr = expr
class Print(Node):
    def __init__(self, exprs, line=None):
        self.exprs = exprs
        self.line = line
class If(Node):
    def __init__(self, cond, then_b, else_b): self.cond, self.then_b, self.else_b = cond, then_b, else_b
class ExprStmt(Node):
    def __init__(self, expr): self.expr = expr
class Call(Node):
    def __init__(self, name, args): self.name, self.args = name, args
class Bin(Node):
    def __init__(self, op,l,r): self.op, self.l, self.r = op,l,r
class Var(Node):
    def __init__(self, name): self.name = name
class Int(Node):
    def __init__(self, val): self.val = int(val)
class Str(Node):
    def __init__(self, val, line=None):
        self.val = val
        self.line = line
class Bool(Node):
    def __init__(self, val): self.val = bool(val)
class Switch(Node):
    def __init__(self, cases, default):
        self.cases = cases  # List of (condition, block) tuples
        self.default = default  # Optional default block
# ============================ PARSER (recursive descent) ============================

class Parser:
    def __init__(self, toks):
        self.toks = toks; self.i=0
    def cur(self): return self.toks[self.i]
    def eat(self, kind=None, val=None):
        t = self.cur()
        if kind and t.kind!=kind:
            raise SyntaxError(f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Expected {kind}, got {t.kind}")
        if val and t.val!=val:
            raise SyntaxError(f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Expected {val}, got {t.val}")
        self.i+=1; return t

    def skip_newlines(self):
        while self.cur().kind == 'NL':
            self.eat('NL')

    def expr_until(self, end_syms):
        """Parse an expression until one of the end symbols is encountered."""
        self.skip_newlines()
        if self.cur().kind == 'SYM' and self.cur().val in end_syms:
            raise SyntaxError(
                f"ildzc[parser:{self.cur().pos}] error at {self.cur().line}:{self.cur().col}: "
                f"Expected expression, got {self.cur().val}"
            )
        node = self.bin_eq(end_syms)  # Pass end_syms to bin_eq
        return node
    
    def parse(self):
        decls = []
        self.skip_newlines()
        while self.cur().kind != 'EOF':
            self.skip_newlines()
            if (self.cur().kind == 'ID' and self.i + 1 < len(self.toks) and 
                self.toks[self.i + 1].kind == 'SYM' and self.toks[self.i + 1].val == ':'):
                decls.append(self.fn())
            elif self.cur().kind == 'SYM' and self.cur().val == ':':
                decls.append(self.fn())
            else:
                decls.append(self.top_stmt())
        return Program(decls)

    def _is_kw(self, kw): return self.cur().kind=='KW' and self.cur().val==kw

    def fn(self):
        if self.cur().kind == 'ID' and self.i + 1 < len(self.toks) and self.toks[self.i + 1].kind == 'SYM' and self.toks[self.i + 1].val == ':':
            name = self.eat('ID').val
            self.eat('SYM', ':')
        else:
            t = self.cur()
            raise SyntaxError(f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Expected function name followed by ':'")
        params = []
        param_types = []
        while self.cur().kind == 'ID':
            param_name = self.eat('ID').val
            params.append(param_name)
            param_types.append('int')  # Default type, to be updated
            if self.cur().kind != 'SYM' or self.cur().val != ',':
                break
            self.eat('SYM', ',')
        self.eat('SYM', '<')
        self.skip_newlines()
        body = self.block(end_syms=['>'])
        self.eat('SYM', '>')
        self.skip_newlines()
        # Infer parameter types from body
        for stmt in body.stmts:
            if isinstance(stmt, Print):
                for expr in stmt.exprs:
                    if isinstance(expr, Var) and expr.name in params:
                        param_types[params.index(expr.name)] = 'string'
        return Fn(name, params, body, param_types)

    def block(self, end_syms=None):
        if end_syms is None:
            end_syms = ('}',)
        stmts = []
        while not (self.cur().kind == 'SYM' and self.cur().val in end_syms) and self.cur().kind != 'EOF':
            self.skip_newlines()
            if self.cur().kind == 'SYM' and self.cur().val in end_syms:
                break
            stmt = self.stmt()
            if stmt is not None:
                stmts.append(stmt)
            self.skip_newlines()  # Ensure newlines are skipped after each statement
        return Block(stmts)

    def top_stmt(self):
        self.skip_newlines()
        if self.cur().kind == 'ID' and self.i + 1 < len(self.toks) and self.toks[self.i + 1].kind in ('INT', 'STR', 'ID'):
            return self.let()
        if self._is_kw('pr'): 
            return self.print_stmt()
        if self._is_kw('if'): 
            return self.if_stmt()
        if self.cur().kind == 'SYM' and self.cur().val == '{': 
            self.eat('SYM', '{')
            b = self.block()
            self.eat('SYM', '}')
            return b
        if self.cur().kind == 'ID':
            t = self.cur()
            raise SyntaxError(
                f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Unexpected standalone identifier {t.val!r}"
            )
        return ExprStmt(self.expr())

    def stmt(self):
        self.skip_newlines()
        if self.cur().kind == 'ID' and self.i + 1 < len(self.toks) and self.toks[self.i + 1].kind in ('INT', 'STR', 'ID'):
            return self.let()
        if self._is_kw('pr'):
            return self.print_stmt()
        if self._is_kw('if'):
            return self.if_stmt()
        if self.cur().kind == 'SYM' and self.cur().val == '{':
            self.eat('SYM', '{')
            b = self.block()
            self.eat('SYM', '}')
            return b
        if self.cur().kind == 'KW' and self.cur().val == 'ret':
            self.eat('KW', 'ret')
            self.skip_newlines()
            expr = self.expr()
            return Return(expr)
        if self.cur().kind == 'NL':
            self.eat('NL')
            return None
        # Only parse ExprStmt if the token is valid for an expression
        if self.cur().kind in ('INT', 'STR', 'ID', 'SYM') and self.cur().val in ('(', '-', ':'):
            return ExprStmt(self.expr())
        t = self.cur()
        raise SyntaxError(
            f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Unexpected token {t.kind} {t.val!r}"
        )

    def print_stmt(self):
        start_line = self.cur().line
        self.eat('KW', 'pr')
        self.skip_newlines()
        exprs = []
        if self.cur().kind == 'SYM' and self.cur().val == ':':
            self.eat('SYM', ':')
            name = self.eat('ID').val
            args = []
            while self.cur().kind in ('INT', 'STR', 'ID'):
                args.append(self.expr())
                self.skip_newlines()  # Skip newlines after each argument
                if self.cur().kind != 'SYM' or self.cur().val != ',':
                    break
                self.eat('SYM', ',')
            exprs.append(Call(name, args))
        else:
            while self.cur().kind in ('INT', 'STR', 'ID'):
                exprs.append(self.expr())
                self.skip_newlines()  # Skip newlines after each expression
                if self.cur().kind != 'SYM' or self.cur().val != ',':
                    break
                self.eat('SYM', ',')
        self.skip_newlines()
        return Print(exprs, start_line)

def if_stmt(self):
    cases = []
    default = None
    self.eat('KW', 'if')
    self.skip_newlines()
    left = self.expr()
    self.skip_newlines()
    if self.cur().kind not in ('OP', 'SYM') or self.cur().val not in ('==', '!=', '<', '>', '<=', '>='):
        t = self.cur()
        raise SyntaxError(f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Expected comparison operator, got {t.kind} {t.val!r}")
    op = self.eat().val
    self.skip_newlines()
    right = self.expr()
    cond = Bin(op, left, right)
    self.skip_newlines()
    then_block = self.block(end_syms=("''",))
    cases.append((cond, then_block))
    while self.cur().kind == 'SYM' and self.cur().val == "''":
        self.eat('SYM', "''")
        self.skip_newlines()
        if self.cur().kind == 'KW' and self.cur().val == 'if':
            self.eat('KW', 'if')
            self.skip_newlines()
            left = self.expr()
            self.skip_newlines()
            if self.cur().kind not in ('OP', 'SYM') or self.cur().val not in ('==', '!=', '<', '>', '<=', '>='):
                t = self.cur()
                raise SyntaxError(f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Expected comparison operator, got {t.kind} {t.val!r}")
            op = self.eat().val
            self.skip_newlines()
            right = self.expr()
            cond = Bin(op, left, right)
            self.skip_newlines()
            then_block = self.block(end_syms=("''",))
            cases.append((cond, then_block))
        else:
            default = self.block(end_syms=("'",))
            self.eat('SYM', "'")
            self.skip_newlines()
            break
    if default is None and self.cur().kind == 'SYM' and self.cur().val == "'":
        self.eat('SYM', "'")
        self.skip_newlines()
    return Switch(cases, default)

    def let(self):
        names, exprs, types = [], [], []
        self.skip_newlines()
        while self.cur().kind == 'ID':
            names.append(self.eat('ID').val)
            self.skip_newlines()
            expr = self.expr()
            exprs.append(expr)
            # Infer type from expression
            if isinstance(expr, Int):
                types.append('int')
            elif isinstance(expr, Str):
                types.append('string')
            elif isinstance(expr, Var):
                types.append('int')  # Default to int for variables; improve with context
            elif isinstance(expr, Call):
                types.append('int')  # Assume function calls return int (e.g., add)
            else:
                types.append('int')  # Default fallback
            if self.cur().kind != 'SYM' or self.cur().val != ',':
                break
            self.eat('SYM', ',')
        self.skip_newlines()
        return Let(names, exprs, types)

    # Pratt parser for expressions: precedence: * / > + - > cmp > == !=
    def expr(self, end_syms=None):
        return self.bin_eq(end_syms)

    def bin_eq(self, end_syms=None):
        node = self.bin_cmp(end_syms)
        while self.cur().kind in ('OP', 'SYM') and self.cur().val in ('==', '!=') and (end_syms is None or not (self.cur().kind == 'SYM' and self.cur().val in end_syms)):
            op = self.eat(self.cur().kind).val
            node = Bin(op, node, self.bin_cmp(end_syms))
        return node

    def bin_cmp(self, end_syms=None):
        node = self.bin_add(end_syms)
        while self.cur().kind in ('OP', 'SYM') and self.cur().val in ('<', '>', '<=', '>=') and (end_syms is None or not (self.cur().kind == 'SYM' and self.cur().val in end_syms)):
            op = self.eat(self.cur().kind).val
            node = Bin(op, node, self.bin_add(end_syms))
        return node

    def bin_add(self, end_syms=None):
        node = self.bin_mul(end_syms)
        while self.cur().kind == 'SYM' and self.cur().val in ('+', '-') and (end_syms is None or not (self.cur().kind == 'SYM' and self.cur().val in end_syms)):
            op = self.eat('SYM').val
            node = Bin(op, node, self.bin_mul(end_syms))
        return node

    def bin_mul(self, end_syms=None):
        node = self.unary(end_syms)
        while self.cur().kind == 'SYM' and self.cur().val in ('*', '/') and (end_syms is None or not (self.cur().kind == 'SYM' and self.cur().val in end_syms)):
            op = self.eat('SYM').val
            node = Bin(op, node, self.unary(end_syms))
        return node

    def unary(self, end_syms=None):
        t = self.cur()
        if t.kind == 'SYM' and t.val == '-' and (end_syms is None or not (t.kind == 'SYM' and t.val in end_syms)):
            self.eat('SYM', '-')
            return Bin('*', Int(-1), self.unary(end_syms))
        return self.primary(end_syms)

    def primary(self, end_syms=None):
        t = self.cur()

        # Handle unexpected newline by stopping expression parsing
        if t.kind == 'NL':
            raise SyntaxError(
                f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Unexpected newline in expression"
            )

        # Stop if we hit an end symbol
        if end_syms and t.kind == 'SYM' and t.val in end_syms:
            raise SyntaxError(
                f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Unexpected end of expression at {t.val}"
            )

        # Handle `ret` keyword as a special expression
        if t.kind == 'KW' and t.val == 'ret':
            self.eat('KW', 'ret')
            self.skip_newlines()
            expr = self.expr(end_syms)  # Pass end_syms to nested expression
            return Return(expr)

        if t.kind == 'SYM' and t.val == ':':
            self.eat('SYM', ':')
            name = self.eat('ID').val
            args = []
            while self.cur().kind in ('INT', 'STR', 'ID', 'SYM') and not (self.cur().kind == 'SYM' and self.cur().val in (')', ',', '>', 'NL') + (end_syms or ())):
                args.append(self.expr(end_syms))
                if self.cur().kind == 'SYM' and self.cur().val == ',':
                    self.eat('SYM', ',')
                else:
                    break
            return Call(name, args)

        if t.kind == 'INT':
            self.eat('INT')
            return Int(t.val)
        if t.kind == 'STR':
            self.eat('STR')
            return Str(t.val, t.line)
        if t.kind == 'ID':
            name = self.eat('ID').val
            return Var(name)
        if t.kind == 'SYM' and t.val == '(':
            self.eat('SYM', '(')
            self.skip_newlines()
            e = self.expr(end_syms)
            self.eat('SYM', ')')
            return e

        raise SyntaxError(
            f"ildzc[parser:{t.pos}] error at {t.line}:{t.col}: Unexpected token {t.kind} {t.val!r}"
        )

# ============================ CODEGEN to C ============================

class Codegen:
    def __init__(self):
        self.strings = []   # pool C string literals to allow reuse
        self.globals = {}
        self.funcs = []
        self.main_stmts = []
        self.prefix_cache = {}

    def c_string(self, s):
        # Avoid duplicates: return existing name if string already added
        for name, val in self.strings:
            if val == s:
                return name
        esc = s.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')
        name = f'_S{len(self.strings)}'
        self.strings.append((name, esc))
        return name

    def collect_strings_expr(self, e):
        if isinstance(e, Str):
            self.c_string(e.val)
        elif isinstance(e, Bin):
            self.collect_strings_expr(e.l)
            self.collect_strings_expr(e.r)
        elif isinstance(e, Call):
            for arg in e.args:
                self.collect_strings_expr(arg)
        elif isinstance(e, Return):
            self.collect_strings_expr(e.expr)
        elif isinstance(e, Let):
            for expr in e.exprs:
                self.collect_strings_expr(expr)
        elif isinstance(e, Print):
            for expr in e.exprs:
                self.collect_strings_expr(expr)
        elif isinstance(e, If):
            self.collect_strings_expr(e.cond)
            for stmt in e.then_b.stmts:
                self.collect_strings_stmt(stmt)
            if e.else_b:
                for stmt in e.else_b.stmts:
                    self.collect_strings_stmt(stmt)
        elif isinstance(e, ExprStmt):
            self.collect_strings_expr(e.expr)
        elif isinstance(e, Switch):
            for cond, block in e.cases:
                self.collect_strings_expr(cond)
                for stmt in block.stmts:
                    self.collect_strings_stmt(stmt)
            if e.default:
                for stmt in e.default.stmts:
                    self.collect_strings_stmt(stmt)
        # Add more cases if needed

    def collect_strings_stmt(self, stmt):
        if isinstance(stmt, Let):
            for expr in stmt.exprs:
                self.collect_strings_expr(expr)
        elif isinstance(stmt, Return):
            self.collect_strings_expr(stmt.expr)
        elif isinstance(stmt, Print):
            for expr in stmt.exprs:
                self.collect_strings_expr(expr)
        elif isinstance(stmt, If):
            self.collect_strings_expr(stmt.cond)
            for s in stmt.then_b.stmts:
                self.collect_strings_stmt(s)
            if stmt.else_b:
                for s in stmt.else_b.stmts:
                    self.collect_strings_stmt(s)
        elif isinstance(stmt, ExprStmt):
            self.collect_strings_expr(stmt.expr)
        elif isinstance(stmt, Switch):
            for cond, block in stmt.cases:
                self.collect_strings_expr(cond)
                for s in block.stmts:
                    self.collect_strings_stmt(s)
            if stmt.default:
                for s in stmt.default.stmts:
                    self.collect_strings_stmt(s)
        elif isinstance(stmt, Block):
            for s in stmt.stmts:
                self.collect_strings_stmt(s)
        # Add more if your AST has other stmt types

    def collect_prefix_strings(self, stmts, filename):
        self.current_filename = filename
        for s in stmts:
            if isinstance(s, Print):
                prefix_str = f"{filename}[{s.line}] "
                if prefix_str not in self.prefix_cache:
                    self.prefix_cache[prefix_str] = self.c_string(prefix_str)
            # Recursively collect from nested blocks/statements
            if hasattr(s, 'then_b') and s.then_b:
                self.collect_prefix_strings(s.then_b.stmts, filename)
            if hasattr(s, 'else_b') and s.else_b:
                self.collect_prefix_strings(s.else_b.stmts, filename)
            if isinstance(s, Switch):
                for _, block in s.cases:
                    self.collect_prefix_strings(block.stmts, filename)
                if s.default:
                    self.collect_prefix_strings(s.default.stmts, filename)
            if isinstance(s, Block):
                self.collect_prefix_strings(s.stmts, filename)

    def emit_program(self, prog: Program):
        self.current_filename = "t.ildz"  # or set dynamically
        for d in prog.decls:
            if isinstance(d, Fn):
                self.funcs.append(d)
                for stmt in d.body.stmts:
                    self.collect_strings_stmt(stmt)
                self.collect_prefix_strings(d.body.stmts, self.current_filename)
            else:
                self.main_stmts.append(d)
                self.collect_strings_stmt(d)
                self.collect_prefix_strings([d], self.current_filename)

        return self.render()

    def render(self):
        out = []
        out.append("#include <stdio.h>")
        out.append("#include <stdint.h>")
        out.append("#include <stdbool.h>")

        # Emit all string literals collected
        for name, val in self.strings:
            out.append(f'static const char {name}[] = "{val}";')

        # Forward declare functions
        for fn in self.funcs:
            out.append(f"static int {fn.name}({', '.join(['int '+p for p in fn.params])});")

        # Emit function bodies
        for fn in self.funcs:
            out += self.emit_fn(fn)

        # Emit main function
        out.append("int main(void){")
        out += self.emit_block(Block(self.main_stmts), indent=1)
        out.append("  return 0;")
        out.append("}")

        return "\n".join(out)

    def emit_fn(self, fn: Fn):
        param_decls = []
        for param, ptype in zip(fn.params, fn.param_types):
            c_type = 'const char*' if ptype == 'string' else 'int'
            param_decls.append(f"{c_type} {param}")
        lines = [f"static void {fn.name}({', '.join(param_decls)})" + " {",
                 *self.emit_block(fn.body, indent=1),
                 "}"]
        return lines

    def emit_block(self, block: Block, indent=0):
        lines = []
        ind = "  " * indent
        for s in block.stmts:
            if isinstance(s, Let):
                for name, expr, ptype in zip(s.names, s.exprs, s.types):
                    expr_code, kind = self.emit_expr(expr)
                    c_type = 'const char*' if ptype == 'string' else 'int'
                    lines += [f'{ind}{c_type} {name} = {expr_code};']
            elif isinstance(s, Return):
                expr, kind = self.emit_expr(s.expr)
                lines += [f'{ind}return {expr};']
            elif isinstance(s, Print):
                prefix_str = f"{self.current_filename}[{s.line}] "
                prefix_name = self.prefix_cache[prefix_str]
                for expr in s.exprs:
                    expr_code, kind = self.emit_expr(expr)
                    if kind == 'string':
                        lines += [f'{ind}printf("%s%s\\n", {prefix_name}, {expr_code});']
                    else:  # Convert int to string for printing
                        lines += [f'{ind}char buf[32];']
                        lines += [f'{ind}snprintf(buf, sizeof(buf), "%d", {expr_code});']
                        lines += [f'{ind}printf("%s%s\\n", {prefix_name}, buf);']
            elif isinstance(s, If):
                cond, _ = self.emit_expr(s.cond)
                lines += [f'{ind}if ({cond})' + ' {',
                          *self.emit_block(s.then_b, indent + 1),
                          ind + '}']
                if s.else_b:
                    lines[-1] += ' else {'
                    lines += self.emit_block(s.else_b, indent + 1)
                    lines += [ind + '}']
            elif isinstance(s, Switch):
                for i, (cond, then_b) in enumerate(s.cases):
                    cond_code, _ = self.emit_expr(cond)
                    if i == 0:
                        lines += [f'{ind}if ({cond_code})' + ' {']
                    else:
                        lines[-1] += f' else if ({cond_code})' + ' {'
                    lines += self.emit_block(then_b, indent + 1)
                    lines += [ind + '}']
                if s.default:
                    lines[-1] += ' else {'
                    lines += self.emit_block(s.default, indent + 1)
                    lines += [ind + '}']
            elif isinstance(s, ExprStmt):
                expr, _ = self.emit_expr(s.expr)
                lines += [f'{ind}(void)({expr});']
            else:
                raise NotImplementedError(f"stmt {s}")
        return lines

    def emit_expr(self, e):
        if isinstance(e, Int):  return (str(e.val), 'int')
        if isinstance(e, Bool): return ("1" if e.val else "0", 'int')
        if isinstance(e, Str):
            sname = self.c_string(e.val)
            return (sname, 'string')
        if isinstance(e, Var):
            return (e.name, 'int')
        if isinstance(e, Call):
            args = []
            for arg in e.args:
                arg_code, arg_type = self.emit_expr(arg)
                if self.funcs and e.name in [f.name for f in self.funcs]:
                    func = next(f for f in self.funcs if f.name == e.name)
                    if func.param_types and func.param_types[0] == 'string' and arg_type == 'int':
                        temp_var = f"_tmp_{len(self.strings)}"
                        self.strings.append((temp_var, ""))
                        lines = [f'char {temp_var}[32];',
                                 f'snprintf({temp_var}, sizeof({temp_var}), "%d", {arg_code});']
                        args.append(temp_var)
                        self.main_stmts.extend(lines) if not hasattr(self, 'current_block_lines') else self.current_block_lines.extend(lines)
                    else:
                        args.append(arg_code)
                else:
                    args.append(arg_code)
            return_type = 'void'
            if self.funcs and e.name in [f.name for f in self.funcs]:
                return_type = next(f.return_type for f in self.funcs if f.name == e.name)
            return (f"{e.name}({', '.join(args)})", return_type)
        if isinstance(e, Bin):
            l, lk = self.emit_expr(e.l)
            r, rk = self.emit_expr(e.r)
            if lk != rk:
                raise NotImplementedError(f"Type mismatch in binary op {e.op}: {lk} vs {rk}")
            if e.op in ('+', '-', '*', '/', '<', '>', '<=', '>=', '==', '!='):
                return (f"({l} {e.op} {r})", 'int')
            raise NotImplementedError(f"op {e.op}")
        raise NotImplementedError(f"expr {e}")

# ============================ DRIVER ============================

CANDIDATE_COMPILERS = [
    ("clang", []),
    ("gcc", []),
    ("tcc", []),
    ("cl", ["/nologo"]),
]

def find_compiler():
    for c, extra in CANDIDATE_COMPILERS:
        try:
            subprocess.run([c, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return c, extra
        except Exception:
            if c=="cl":
                try:
                    subprocess.run(["cl"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return c, ["/nologo"]
                except Exception:
                    pass
    raise RuntimeError("No C compiler found (clang/gcc/tcc/cl). Install one and retry.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python t.py <source.ildz> [--emit-c out.c] [--only-c]")
        print("\nExample program:\n")
        print(textwrap.dedent(r'''
            pr "Program started" ; print statement
            x 10, y 20 ; two separate declarations
            if x < y
                pr "x < y", x + y ; two separate print statements
            '' ; end of true branch
                pr "nope"
            ' ; end of false branch
            pr :add 3, 4 ; print result of function call
            f:add a, b<ret a + b> ; function def
        '''))
        sys.exit(0)

    src_path = pathlib.Path(sys.argv[1])
    src = src_path.read_text(encoding="utf-8")
    # compile source
    toks = lex(src)
    ast = Parser(toks).parse()
    cg  = Codegen()
    cg.current_filename = src_path.name
    c_src = cg.emit_program(ast)
    if "--emit-c" in sys.argv:
        out_idx = sys.argv.index("--emit-c")+1
        outp = sys.argv[out_idx] if out_idx < len(sys.argv) else "out.c"
        pathlib.Path(outp).write_text(c_src, encoding="utf-8")
        print(f"Wrote {outp}")
    if "--only-c" in sys.argv:
        print("\n--- GENERATED C ---\n")
        print(c_src)
        sys.exit(0)
    # compile and run
    tmp = tempfile.mkdtemp(prefix="ildz_")
    cfile = os.path.join(tmp, "out.c")
    with open(cfile, "w", encoding="utf-8") as f:
        f.write(c_src)

    cc, extra = find_compiler()
    exe = os.path.join(tmp, src_path.stem + (".exe" if os.name=="nt" else ""))
    if cc == "cl":
        cmd = ["cl"] + extra + [cfile, "/Fe:"+exe]
    else:
        cmd = [cc] + extra + [cfile, "-o", exe]
    print(">>", " ".join(shlex.quote(x) for x in cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0: raise RuntimeError("C compilation failed")

    print(">>", exe)
    run = subprocess.run([exe], capture_output=False)
    if run.returncode != 0: raise RuntimeError("Program exited with non-zero status")
    print(f"Built and ran: {exe}\n(Temp dir: {tmp})")

# Generate the .exe? This code below is from another prototype..
import struct
TEXT_RVA = 0x1000
IDATA_RVA = 0x2000

def build_idata():
    kernel_name = b"kernel32.dll\x00"
    func_name = b"\x00\x00ExitProcess\x00"

    desc_rva = IDATA_RVA
    ilt_rva  = IDATA_RVA + 0x28
    iat_rva  = ilt_rva + 8
    name_rva = iat_rva + 8
    dll_rva  = name_rva + len(func_name)

    import_desc = struct.pack("<IIIII",
        ilt_rva, 0, 0, dll_rva, iat_rva
    )

    idata = bytearray()
    idata += import_desc
    idata += b"\x00" * 20           # null descriptor
    idata += struct.pack("<Q", name_rva)  # ILT
    idata += b"\x00" * 8
    idata += struct.pack("<Q", name_rva)  # IAT
    idata += b"\x00" * 8
    idata += func_name
    idata += kernel_name

    return bytes(idata), iat_rva


def write_ildz_compiler(path="ildz.exe"):
    FILE_ALIGN = 0x200
    SECT_ALIGN = 0x1000
    TEXT_RAW = FILE_ALIGN
    IDATA_RAW = FILE_ALIGN + FILE_ALIGN

    code = (
        b"\x31\xC9"                          # xor ecx, ecx
        + b"\x48\xA1" + struct.pack("<Q", 0) # mov rax, [IAT placeholder]
        + b"\xFF\xD0"                        # call rax
    )
    
    # --- DOS header ---
    dos = b"MZ" + b"\x00" * 58
    e_lfanew = 0x80
    dos += struct.pack("<I", e_lfanew)
    dos += b"\x00" * (e_lfanew - len(dos))

    # --- PE signature ---
    pe_sig = b"PE\x00\x00"

    # --- COFF file header ---
    file_header = struct.pack(
        "<HHIIIHH",
        0x8664,    # Machine: x86-64
        2,         # NumberOfSections
        0, 0, 0,
        0xF0,      # SizeOfOptionalHeader
        0x22       # Characteristics
    )

    # --- Optional header (PE32+) ---
    optional_header = struct.pack(
        "<HBBIII"       # Magic, Linker, SizeOfCode/InitData/UninitData
        "II"            # AddressOfEntryPoint, BaseOfCode
        "QII"           # ImageBase, SectionAlignment, FileAlignment
        "HHHHHH"        # Major/Minor OS, Image, Subsystem versions
        "III"           # Win32VersionValue, SizeOfImage, SizeOfHeaders
        "HH"            # Checksum, Subsystem
        "QQQQ"          # StackReserve, StackCommit, HeapReserve, HeapCommit
        "II",           # LoaderFlags, NumberOfRvaAndSizes
        0x20B, 0, 0, len(code), 0, 0,   # first 6 fields
        0x1000, 0x1000, 0x140000000, SECT_ALIGN, FILE_ALIGN,
        6, 0, 0, 0, 6, 0,
        0, 0x3000, FILE_ALIGN,
        0, 3,
        0x100000, 0x1000, 0x100000, 0x1000,
        0, 16
    )




    idata, exitprocess_iat = build_idata()
    code = code.replace(struct.pack("<Q", 0), struct.pack("<Q", exitprocess_iat))
    code_padded = code + b"\x00" * (FILE_ALIGN - len(code))

    idata_section = struct.pack(
        "<8sIIIIIIHHI",
        b".idata\x00\x00",
        len(idata),
        IDATA_RVA,
        FILE_ALIGN,
        IDATA_RAW,
        0, 0, 0, 0,
        0x40000040
    )

    data_dirs = (
        struct.pack("<II", IDATA_RVA, len(idata)) +
        b"\x00" * (15 * 8)
    )

    # --- .text section header ---
    section_header = struct.pack(
        "<8sIIIIIIHHI",
        b".text\x00\x00\x00",
        len(code),
        TEXT_RVA,
        FILE_ALIGN,
        TEXT_RAW,
        0, 0, 0, 0,
        0x60000020
    )

    with open(path, "wb") as f:
        f.write(dos)
        f.write(pe_sig)
        f.write(file_header)
        f.write(optional_header)
        f.write(data_dirs)

        # section headers (ORDER MATTERS)
        f.write(section_header)     # .text
        f.write(idata_section)      # .idata

        # pad headers to FILE_ALIGN
        header_pad = (FILE_ALIGN - (f.tell() % FILE_ALIGN)) % FILE_ALIGN
        f.write(b"\x00" * header_pad)

        # .text section body
        f.write(code_padded)

        # pad to next section
        f.write(b"\x00" * (FILE_ALIGN - len(code_padded)))

        # .idata section body
        f.write(idata)


    print("ildz.exe written")

if __name__ == "__main__":
    write_ildz_compiler()









import re
from dataclasses import dataclass
from typing import List, Union, Dict, Optional, Set
import sys
import os
import subprocess
import inspect
import uuid
from div import get_libdivide_helper_asm
from emit import emit_exit, platform_windows, platform_linux
from utils import HELP_MESSAGE, nasm_string_literal, VALID_FLAGS

keywords = {'er', 'f', 'if', 'it', 'nu', 'pr', 'ret', 's'}
# Flags
nl = False
release = False
verbose_generator = False
verbose_parser = False
verbose_optimizer = False
verbose_lexer = False
code_reachable = True

# Token types
@dataclass
class Token:
    type: str
    value: str
    line: int
    column: int

# AST Nodes
@dataclass
class Number:
    value: int

@dataclass
class Variable:
    name: str

@dataclass
class StringLiteral:
    value: str

@dataclass
class BinaryOp:
    op: str
    left: Union['Number', 'Variable', 'BinaryOp']
    right: Union['Number', 'Variable', 'BinaryOp']

@dataclass
class Assignment:
    var: str
    expr: Union[Number, Variable, BinaryOp, StringLiteral]

@dataclass
class Declaration:
    var: str
    type_name: str
    value: Union[Number, StringLiteral, BinaryOp, None] = None

@dataclass
class Print:
    arg: Union[Variable, StringLiteral]
    line: int
    is_error: bool = False

@dataclass
class FunctionCall:
    name: str
    args: List[Union[Variable, StringLiteral, Number]]
    line: int

@dataclass
class IfStatement:
    condition: BinaryOp
    then_block: List[Union[Assignment, 'IfStatement', Print, FunctionCall]]
    line: int
    else_block: List[Union[Assignment, 'IfStatement', Print, FunctionCall]] = None

@dataclass
class FunctionDefinition:
    name: str
    params: List[str]
    param_types: List[str]
    body: List[Union[Assignment, IfStatement, Print, FunctionCall]]
    line: int

@dataclass
class ReturnStatement:
    value: Optional[object]  # expression or None if no return value

@dataclass
class LoopStatement:
    count: Union[Number, Variable, BinaryOp]
    body: List[Union[Assignment, IfStatement, Print, FunctionCall, 'LoopStatement', 'BreakStatement']]
    line: int

@dataclass
class BreakStatement:
    line: int

class Lexer:
    def __init__(self, code: str, verbose: bool = False):
        self.code = code
        self.verbose = verbose

    def lex(self) -> List[Token]:
        tokens = []
        pos = 0
        line = 1
        column = 1

        while pos < len(self.code):
            char = self.code[pos]

            if char.isspace():
                if char == '\n':
                    line += 1
                    column = 1
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Newline encountered at {line}:{column}")
                else:
                    column += 1
                pos += 1
                continue

            if char == ';':
                if self.verbose:
                    print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Comment started at {line}:{column}")
                pos += 1
                column += 1
                # Check for multiline comment
                if pos < len(self.code) and self.code[pos] == ';':
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Multiline comment started ';;' at {line}:{column}")
                    pos += 1
                    column += 1
                    # Scan until closing ';;'
                    while pos < len(self.code) - 1:
                        if self.code[pos] == ';' and pos + 1 < len(self.code) and self.code[pos + 1] == ';':
                            pos += 2
                            column += 2
                            if self.verbose:
                                print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Multiline comment ended ';;' at {line}:{column}")
                            break
                        if self.code[pos] == '\n':
                            line += 1
                            column = 1
                        else:
                            column += 1
                        pos += 1
                    else:
                        raise SyntaxError(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Unterminated multiline comment at {line}:{column}")
                    continue
                # Handle single-line comment
                while pos < len(self.code) and self.code[pos] != ';' and self.code[pos] != '\n':
                    pos += 1
                    column += 1
                if pos < len(self.code) and self.code[pos] == ';':
                    pos += 1
                    column += 1
                if self.verbose:
                    print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Single line comment skipped at {line}:{column}")
                continue

            if char.isalpha() or char == '_' or char == ':':
                if char == 'f' and pos + 1 < len(self.code) and self.code[pos + 1] == ':':
                    id_match = re.match(r'f:([a-zA-Z_][a-zA-Z0-9_]*)', self.code[pos:])
                    if id_match:
                        value = id_match.group(1)
                        tokens.append(Token('FUNC_DEF', value, line, column))
                        if self.verbose:
                            print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Function definition 'f:{value}' at {line}:{column}")
                        pos += len(id_match.group(0))
                        column += len(id_match.group(0))
                        # Check for opening parenthesis
                        while pos < len(self.code) and self.code[pos].isspace() and self.code[pos] != '\n':
                            pos += 1
                            column += 1
                        if pos < len(self.code) and self.code[pos] == '(':
                            tokens.append(Token('(', '(', line, column))
                            if self.verbose:
                                print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Opening parenthesis at {line}:{column}")
                            pos += 1
                            column += 1
                        continue
                elif char == ':':
                    if pos + 1 < len(self.code) and self.code[pos + 1] == '|':
                        tokens.append(Token('BREAK', ':|', line, column))
                        if self.verbose:
                            print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Break ':|' at {line}:{column}")
                        pos += 2
                        column += 2
                        continue
                    id_match = re.match(r':([a-zA-Z_][a-zA-Z0-9_]*)', self.code[pos:])
                    if id_match:
                        value = id_match.group(1)
                        tokens.append(Token('FUNC_CALL', value, line, column))
                        if self.verbose:
                            print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Function call ':{value}' at {line}:{column}")
                        pos += len(id_match.group(0))
                        column += len(id_match.group(0))
                        continue
                    tokens.append(Token('LOOP_END', ':', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Loop end ':' at {line}:{column}")
                    pos += 1
                    column += 1
                    continue
                else:
                    id_match = re.match(r'[a-zA-Z_][a-zA-Z0-9_]*', self.code[pos:])
                    if id_match:
                        value = id_match.group(0)
                        token_type = 'keyword' if value in keywords else 'ID'
                        tokens.append(Token(token_type, value, line, column))
                        if self.verbose:
                            print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Identifier '{value}' as {token_type} at {line}:{column}")
                        pos += len(value)
                        column += len(value)
                        continue
                    raise SyntaxError(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Invalid function call at {line}:{column}")
                id_match = re.match(r'[a-zA-Z_][a-zA-Z0-9_]*', self.code[pos:])
                if id_match:
                    value = id_match.group(0)
                    token_type = 'keyword' if value in keywords else 'ID'
                    tokens.append(Token(token_type, value, line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Identifier '{value}' as {token_type} at {line}:{column}")
                    pos += len(value)
                    column += len(value)
                    continue

            if char.isdigit():
                num_match = re.match(r'[0-9]+(\.[0-9]+)?', self.code[pos:])
                if num_match:
                    tokens.append(Token('number', num_match.group(0), line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Number literal '{num_match.group(0)}' at {line}:{column}")
                    pos += len(num_match.group(0))
                    column += len(num_match.group(0))
                    continue

            if char == '"':
                end_pos = pos + 1
                string_chars = []
                escaped = False

                while end_pos < len(self.code):
                    c = self.code[end_pos]

                    if escaped:
                        if c == '\n':
                            # Skip this newline completely (escaped newline)
                            line += 1
                            column = 0
                        else:
                            string_chars.append(c)
                            column += 1
                        escaped = False

                    elif c == '|':
                        escaped = True
                        column += 1

                    elif c == '"':
                        # End of string
                        break

                    else:
                        string_chars.append(c)
                        if c == '\n':
                            line += 1
                            column = 0
                        else:
                            column += 1

                    end_pos += 1

                if end_pos >= len(self.code):
                    raise SyntaxError(
                        f"ildzc[lexer:{inspect.currentframe().f_lineno}] Unterminated string literal at {line}:{column}"
                    )

                string_value = ''.join(string_chars)
                tokens.append(Token('string', string_value, line, column))
                if self.verbose:
                    print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] String literal \"{string_value}\" at {line}:{column}")

                pos = end_pos + 1
                column += 1
                continue

            if char in '+-*/><,()\'':
                if char == '>' and pos + 1 < len(self.code) and self.code[pos + 1] == '=':
                    tokens.append(Token('GE', '>=', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] '>=' operator at {line}:{column}")
                    pos += 2
                    column += 2
                elif char == '<' and pos + 1 < len(self.code) and self.code[pos + 1] == '=':
                    tokens.append(Token('LE', '<=', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] '<=' operator at {line}:{column}")
                    pos += 2
                    column += 2
                elif char == '!' and pos + 1 < len(self.code) and self.code[pos + 1] == '=':
                    tokens.append(Token('NE', '!=', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] '!=' operator at {line}:{column}")
                    pos += 2
                    column += 2
                elif char == '=' and pos + 1 < len(self.code) and self.code[pos + 1] == '=':
                    tokens.append(Token('EQ', '==', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] '==' operator at {line}:{column}")
                    pos += 2
                    column += 2
                elif char == '\'' and pos + 1 < len(self.code) and self.code[pos + 1] == '\'':
                    tokens.append(Token('DOUBLE_QUOTE', '\'\'' , line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Double single-quote '' at {line}:{column}")
                    pos += 2
                    column += 2
                elif char == '\'':
                    tokens.append(Token('SINGLE_QUOTE', '\'', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Single quote ' at {line}:{column}")
                    pos += 1
                    column += 1
                elif char == ',':
                    prev_pos = pos - 1
                    while prev_pos >= 0 and self.code[prev_pos].isspace() and self.code[prev_pos] != '\n':
                        prev_pos -= 1
                    is_if_context = False
                    if prev_pos >= 0:
                        prev_token = ''
                        temp_pos = pos - 1
                        while temp_pos >= 0 and self.code[temp_pos] != '\n':
                            id_match = re.match(r'[a-zA-Z_][a-zA-Z0-9_]*', self.code[temp_pos:])
                            if id_match and id_match.group(0) == 'if':
                                prev_token = 'if'
                                break
                            temp_pos -= 1
                        if prev_token == 'if':
                            is_if_context = True
                    tokens.append(Token(',', ',', line, column) if is_if_context else Token('COMMA', ',', line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Comma ',' (if_context={is_if_context}) at {line}:{column}")
                    pos += 1
                    column += 1
                else:
                    tokens.append(Token(char, char, line, column))
                    if self.verbose:
                        print(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Symbol '{char}' at {line}:{column}")
                    pos += 1
                    column += 1
                continue

            raise SyntaxError(f"ildzc[lexer:{inspect.currentframe().f_lineno}] Invalid character '{char}' at {line}:{column}")

        if self.verbose:
            print(f"\033[92m[SUCCESS] ildzc[lexer] Lexing complete. Total tokens: {len(tokens)}\033[0m\n")

        return tokens

class Parser:
    def __init__(self, tokens: List[Token], verbose: bool = False):
        self.tokens = tokens
        self.pos = 0
        self.variables = set()
        self.var_types = {}  # Track variable types: 'number' or 'string'
        self.functions = {}  # Track function definitions: name -> FunctionDefinition
        self.called_functions = set()  # Track called function names
        self.function_calls = []  # Track function calls for later validation
        self.verbose = verbose

    def peek(self) -> Token:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected_type: str, context: str) -> Token:
        token = self.peek()
        if token and token.type == expected_type:
            self.pos += 1
            return token
        raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected '{expected_type}' in {context}, but got {token.type if token else 'EOF'} '{token.value}' at {token.line if token else -1}:{token.column if token else -1}")

    def parse_error(self) -> List[Print]:
        er_token = self.consume('keyword', 'error statement')
        prints = []
        
        while True:
            token = self.peek()
            if not token:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Unexpected end of input after 'er' at line {er_token.line}, column {er_token.column}")
            if token.type == 'string':
                string_value = self.consume('string', 'string literal in error statement').value
                if self.verbose:
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Error statement with string literal '{string_value}' at :{token.line}:{token.column}")
                prints.append(Print(StringLiteral(string_value), er_token.line, is_error=True))  # Set is_error=True
            elif token.type == 'ID':
                var_name = self.consume('ID', 'error statement').value
                if var_name not in self.variables:
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Undefined variable '{var_name}' at {token.line}:{token.column}")
                if self.verbose:
                    print(f"ildzc[parser:{token.line}:{inspect.currentframe().f_lineno}] Error statement with variable '{var_name}' at {token.line}:{token.column}")
                prints.append(Print(Variable(var_name), er_token.line, is_error=True))  # Set is_error=True
            else:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected string or variable after 'er' at {token.line}:{token.column}")
            
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA', 'one-line multiple error statement')
                if self.peek() and self.peek().type in ('string', 'ID'):
                    continue
                else:
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected string or variable after comma at {self.peek().line}:{self.peek().column}")
            break
        
        return prints

    def parse_factor(self) -> Union[Number, Variable, BinaryOp, StringLiteral]:
        token = self.peek()
        if token.type == 'number':
            self.consume('number', 'binary expression')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Number literal with value {token.value} at {token.line}:{token.column}")
            return Number(float(token.value))
        elif token.type == 'string':
            self.consume('string', 'binary expression')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] String literal '{token.value}' at {token.line}:{token.column}")
            return StringLiteral(token.value)
        elif token.type == 'ID':
            var_name = self.consume('ID', 'binary expression').value
            if var_name not in self.variables:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Undefined variable '{var_name}' at {token.line}:{token.column}")
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Variable reference '{var_name}' at {token.line}:{token.column}")
            return Variable(var_name)
        elif token.type == '(':
            self.consume('(', 'binary expression')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Opening parenthesis at {token.line}:{token.column}")
            expr = self.parse_expression()
            self.consume(')', 'binary expression')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Closing parenthesis at {token.line}:{token.column}")
            return expr
        raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Invalid factor '{token.value}' at {token.line}:{token.column}. Expected number, string, variable, or parenthesized expression")

    def parse_term(self) -> Union[Number, Variable, BinaryOp, StringLiteral]:
        left = self.parse_factor()
        while self.peek() and self.peek().type in ('*', '/'):
            op = self.consume(self.peek().type, 'math expression').type
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Binary operator '{op}' at {self.peek().line}:{self.peek().column}")
            right = self.parse_factor()
            left = BinaryOp(op, left, right)
        return left

    def parse_expression(self) -> Union[Number, Variable, BinaryOp, StringLiteral]:
        left = self.parse_term()
        while self.peek() and self.peek().type in ('+', '-', '>', '<', 'GE', 'LE', 'EQ', 'NE'):
            op = self.consume(self.peek().type, 'binary expression').type
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Binary operator '{op}' at {self.peek().line}:{self.peek().column}")
            right = self.parse_term()
            left = BinaryOp(op, left, right)
        return left

    def parse_declaration(self) -> List[Declaration]:
        declarations = []
        type_token = self.consume('keyword', 'variable type declaration')
        type_name = 'string' if type_token.value == 's' else 'number'
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Type declaration '{type_token.value}' ({type_name}) at {self.peek().line}:{self.peek().column}")
        
        while True:
            var = self.consume('ID', 'variable name declaration').value
            if var in self.variables:
                original_token = None
                for t in self.tokens:
                    if t.value == var and t.type == 'ID':
                        original_token = t
                        break
                if original_token is None:
                    raise RuntimeError(f"Internal error: variable '{var}' declared previously at {original_token.line}:{original_token.column} and attempted declared again at {type_token.line}:{type_token.column} but token not found.")
                
                raise SyntaxError(
                    f"ildzc[parser:{inspect.currentframe().f_lineno}] Illegal redefinition at {type_token.line}:{type_token.column} of variable '{var}' "
                    f"already declared at {original_token.line}:{original_token.column}"
                )

            self.variables.add(var)
            self.var_types[var] = type_name
            value = None
            
            if self.peek() and self.peek().type in ('number', 'string') or (type_name == 'number' and self.peek() and self.peek().type in ('ID', '(', '+', '-', '*', '/')):
                if type_name == 'string' and self.peek().type != 'string':
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Illegal assignment of {self.peek().type} value to string variable '{var}' at {self.peek().line}:{self.peek().column}")
                if type_name == 'number' and self.peek().type == 'string':
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Illegal assignment of string value to {type_name} variable '{var}' at {self.peek().line}:{self.peek().column}")
                if type_name == 'number':
                    value = self.parse_expression()
                    if isinstance(value, StringLiteral):
                        raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Illegal assignment of string value to {type_name} variable '{var}' at {self.peek().line if self.peek() else -1}:{self.peek().column if self.peek() else -1}")
                else:
                    token = self.consume('string', 'string name declaration')
                    value = StringLiteral(token.value)
            
            declarations.append(Declaration(var, type_name, value))
            if self.verbose:
                value_str = ""
                if value:
                    if isinstance(value, StringLiteral):
                        value_str = f" with string value '{value.value}'"
                    elif isinstance(value, Number):
                        value_str = f" with number value {value.value}"
                    elif isinstance(value, BinaryOp):
                        value_str = f" with expression {value.op}"
                    elif isinstance(value, Variable):
                        value_str = f" with variable {value.name}"
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Type {type_name} declared with name '{var}'{value_str} at {type_token.line}:{type_token.column}")
            
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA', 'one-line multiple variable declaration')
                if self.peek() and self.peek().type == 'keyword' and self.peek().value in ('nu', 's'):
                    break
                elif self.peek() and self.peek().type == 'ID':
                    continue
                else:
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected identifier or type after comma at {self.peek().line}:{self.peek().column}")
            break
        
        return declarations

    def parse_print(self) -> List[Print]:
        pr_token = self.consume('keyword', 'print statement')
        prints = []
        
        while True:
            token = self.peek()
            if not token:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Unexpected end of input after 'pr' at line {pr_token.line}, column {pr_token.column}")
            if token.type == 'string':
                string_value = self.consume('string', 'string literal in print statement').value
                if self.verbose:
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Print statement with string literal '{string_value}' at {token.line}:{token.column}")
                prints.append(Print(StringLiteral(string_value), pr_token.line))
            elif token.type == 'ID':
                var_name = self.consume('ID', 'print statement').value
                if var_name not in self.variables:
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Undefined variable '{var_name}' at {token.line}:{token.column}")
                if self.verbose:
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Print statement with variable '{var_name}' at {token.line}:{token.column}")
                prints.append(Print(Variable(var_name), pr_token.line))
            else:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected string or variable at {token.line}:{token.column} in print statement")
            
            # Check for comma to continue parsing additional arguments
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA', 'one-line multiple print statement')
                if self.peek() and self.peek().type in ('string', 'ID'):
                    continue
                else:
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected string or variable after comma at {self.peek().line}:{self.peek().column} in one-line multiple print statement")
            break
        
        return prints

    def parse_if_statement(self) -> IfStatement:
        start_token = self.peek()
        if not isinstance(start_token.line, int):
            print(f"ildzc[parser:warning] Invalid start_token.line: {start_token.line} at {start_token.line}:{start_token.column}")
        self.consume('keyword', 'if statement')
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] If statement at {start_token.line}:{start_token.column}")
        # Allow function call or expression as condition
        condition = None
        if self.peek() and self.peek().type == 'FUNC_CALL':
            condition = self.parse_function_call()
            if condition is None:  # Unreachable function call
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Unreachable function call in if condition at {start_token.line}:{start_token.column}")
        else:
            condition = self.parse_expression()
        self.consume(',', 'end of if condition')
        then_block = []
        while self.peek() and self.peek().type not in ('DOUBLE_QUOTE', 'SINGLE_QUOTE'):
            if self.peek().line == start_token.line:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Expected ',' to end if condition at {self.peek().line}:{self.peek().column}")
            stmt = self.parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    then_block.extend(stmt)
                else:
                    then_block.append(stmt)
        
        else_block = None
        if self.peek() and self.peek().type == 'DOUBLE_QUOTE':
            self.consume('DOUBLE_QUOTE', 'breakjump as end of if statement block')
            else_block = []
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Else statement at {self.peek().line}:{self.peek().column}")
            while self.peek() and self.peek().type != 'SINGLE_QUOTE':
                stmt = self.parse_statement()
                if stmt is not None:
                    if isinstance(stmt, list):
                        else_block.extend(stmt)
                    else:
                        else_block.append(stmt)
        
        if not self.peek():
            raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Unexpected end of input, expected 'SINGLE_QUOTE' at {start_token.line}:{self.peek().column if self.peek() else -1}")
        self.consume('SINGLE_QUOTE', 'end of if statement block')
        
        return IfStatement(condition, then_block, start_token.line, else_block)

    def parse_function_definition(self) -> FunctionDefinition:
        start_token = self.consume('FUNC_DEF', 'function definition')
        func_name = start_token.value
        if func_name in self.functions:
            raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Function '{func_name}' redefined at {start_token.line}:{start_token.column}")
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Function definition ':{func_name}' at {start_token.line}:{start_token.column}")
        params = []
        param_types = []
        param_names_seen = set()

        while self.peek() and self.peek().type == 'keyword' and self.peek().value in ('s', 'nu'):
            type_token = self.consume('keyword', 'parameter type')
            type_name = 'string' if type_token.value == 's' else 'nu'
            
            param = self.consume('ID', 'function parameter').value
            
            if param in param_names_seen:
                raise SyntaxError(
                    f"ildzc[parser:{inspect.currentframe().f_lineno}] Duplicate parameter name '{param}' at {start_token.line}:{start_token.column} in function '{func_name}'"
                    f"at {type_token.line}:{type_token.column}"
                )
            
            param_names_seen.add(param)
            params.append(param)
            self.variables.add(param)
            self.var_types[param] = type_name
            param_types.append(type_name)
            
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Parameter '{param}' of type '{type_name}' at {start_token.line}:{start_token.column} in function '{func_name}'")
            
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA', 'function parameter separator')
                while self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'function parameters whitespace')

        self.consume('(', 'function body start')
        body = []

        while self.peek() and self.peek().type == '\n':
            self.consume('\n', 'function body whitespace')

        global code_reachable
        code_reachable = True

        while self.peek() and self.peek().type != ')':
            stmt = self.parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    body.extend(stmt)
                else:
                    body.append(stmt)

            # Set flag in order to remove unreachable code after return statements
            if isinstance(stmt, ReturnStatement):
                code_reachable = False

            while self.peek() and self.peek().type == '\n':
                self.consume('\n', 'function body statement separator')
        self.consume(')', 'function body end')
        func_def = FunctionDefinition(func_name, params, param_types, body, start_token.line)
        self.functions[func_name] = func_def
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Function ':{func_name}' with {len(params)} args and {len(body)} statements at {start_token.line}:{start_token.column}")
        return func_def

    def parse_function_call(self) -> FunctionCall:
        start_token = self.consume('FUNC_CALL', 'function call')
        func_name = start_token.value
        
        global code_reachable
        if code_reachable:
            self.called_functions.add(func_name)
        else:
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Unreachable function call ':{func_name}' at {start_token.line}:{start_token.column}")
            return None
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Function call ':{func_name}' at {start_token.line}:{start_token.column}")
        args = []
        # Parse arguments (if any)
        while self.peek() and self.peek().type in ('ID', 'string', 'number'):
            if self.peek().type == 'ID':
                var_name = self.consume('ID', 'function call argument').value
                if var_name not in self.variables:
                    raise SyntaxError(f"ildzc[parser:{self.peek().line}] Undefined variable '{var_name}' in function call at {start_token.line}:{start_token.column}")
                args.append(Variable(var_name))
            elif self.peek().type == 'string':
                string_value = self.consume('string', 'function call argument').value
                args.append(StringLiteral(string_value))
            elif self.peek().type == 'number':
                num_value = float(self.consume('number', 'function call argument').value)
                args.append(Number(num_value))
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA', 'function call argument separator')
                while self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'function call argument whitespace')
            elif self.peek() and self.peek().type not in ('ID', 'string', 'number'):
                break  # Exit if next token is not an argument
        call = FunctionCall(func_name, args, start_token.line)
        self.function_calls.append(call)
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Function call ':{func_name}' at {start_token.line}:{start_token.column} with {len(args)} arguments")
        return call

    def parse_loop(self) -> 'LoopStatement':
        start_token = self.consume('keyword', 'loop statement')
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Loop statement at {start_token.line}:{start_token.column}")
        count = self.parse_expression()
        self.consume('COMMA', 'end of loop count')
        body = []
        while self.peek() and self.peek().type not in ('LOOP_END',):
            stmt = self.parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    body.extend(stmt)
                else:
                    body.append(stmt)
        self.consume('LOOP_END', 'end of loop body')
        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Loop with {len(body)} statements at {start_token.line}:{start_token.column}")
        return LoopStatement(count, body, start_token.line)

    def parse_return(self) -> ReturnStatement:
        token = self.consume('keyword', 'return statement')  # consume 'ret'
        
        # If next token starts an expression (number, string, ID, '('), parse it
        if self.peek() is None or self.peek().type == '\n' or self.peek().type == ')' or self.peek().type in ('FUNC_CALL', 'FUNC_DEF', 'keyword', 'SINGLE_QUOTE'):
            # No expression to parse; just return
            if self.peek() and self.peek().type == '\n':
                self.consume('\n', 'end of return statement')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Void return at {token.line}:{token.column}")
            return ReturnStatement(None)
        
        # Parse a single expression (enforce single return value)
        expr = self.parse_expression()
        if self.peek() and self.peek().type == ',':
            raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Multiple return values not supported at {self.peek().line}:{self.peek().column}")
        if self.peek() and self.peek().type == '\n':
            self.consume('\n', 'end of return statement')

        if self.verbose:
            print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Return expression at {token.line}:{token.column}")
        return ReturnStatement(expr)

    def parse_statement(self) -> Union[Assignment, List[Declaration], IfStatement, List[Print], FunctionDefinition, FunctionCall, ReturnStatement, LoopStatement, BreakStatement, None]:
        if self.peek() is None:
            return None
        if self.peek().type == 'keyword' and self.peek().value in keywords:
            if self.peek().value == 'nu' or self.peek().value == 's':
                return self.parse_declaration()
            elif self.peek().value == 'it':
                return self.parse_loop()
            elif self.peek().value == 'if':
                return self.parse_if_statement()
            elif self.peek().value == 'pr':
                return self.parse_print()
            elif self.peek().value == 'er':
                return self.parse_error()
            elif self.peek().value == 'ret':
                return self.parse_return()
        elif self.peek().type == 'BREAK':
            start_token = self.consume('BREAK', 'break statement')
            if self.verbose:
                print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Break statement at {start_token.line}:{start_token.column}")
            return BreakStatement(start_token.line)
        elif self.peek().type == 'FUNC_DEF':
            return self.parse_function_definition()
        elif self.peek().type == 'FUNC_CALL':
            return self.parse_function_call()
        elif self.peek().type == 'ID':
            token = self.peek()
            var = self.consume('ID', 'value assignment').value
            if var not in self.variables:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Undefined variable '{var}' at {token.line}:{token.column}")
            
            # Check if the next token is a function call (e.g., "number :something asd, asd")
            if self.peek() and self.peek().type == 'FUNC_CALL':
                func_call = self.parse_function_call()
                if func_call is None:  # Unreachable function call
                    return None
                # Create an Assignment with the function call as the expression
                if self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'end of function call assignment')
                if self.verbose:
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Parsed assignment to variable '{var}' with function call ':{func_call.name}' at {token.line}:{token.column}")
                return Assignment(var, func_call)
            
            # Handle shorthand assignments (y+, y-, y + 3, y - 3)
            if self.peek() and self.peek().type in ('+', '-'):
                op = self.consume(self.peek().type, 'shorthand assignment').type
                right_value = Number(1)  # Default for y+ or y-
                if self.peek() and self.peek().type == 'number':
                    right_value = Number(float(self.consume('number', 'shorthand assignment value').value))
                if self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'end of shorthand assignment')
                expr = BinaryOp(op, Variable(var), right_value)
                if self.var_types.get(var) == 'string':
                    raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Cannot apply {op} to string variable '{var}' at {token.line}:{token.column}")
                if self.verbose:
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] '{op}' assignment to variable '{var}' with value {right_value.value} at {token.line}:{token.column}")
                return Assignment(var, expr)
            
            # Handle regular assignment (y + 1 or full expression)
            expr = self.parse_expression()
            if isinstance(expr, StringLiteral) and self.var_types.get(var) != 'string':
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Cannot assign string to non-string variable '{var}' at {token.line}:{token.column}")
            if isinstance(expr, (Number, BinaryOp)) and self.var_types.get(var) == 'string':
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Cannot assign number to string variable '{var}' at {token.line}:{token.column}")
            
            # Transform y + 1 into Assignment(var, BinaryOp('+', Variable(var), Number(1)))
            if isinstance(expr, BinaryOp) and isinstance(expr.left, Variable) and expr.left.name == var:
                if self.verbose:
                    expr_str = f" with expression {expr.op} (self-referential)"
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Parsed self-referential assignment to variable '{var}'{expr_str} at {token.line}:{token.column}")
                if self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'end of variable value assignment')
                return Assignment(var, expr)
            elif isinstance(expr, (Number, Variable, BinaryOp)):
                # If expr is a standalone number, variable, or complex expression, assume self-referential
                new_expr = expr
                if isinstance(expr, Number):
                    new_expr = BinaryOp('+', Variable(var), expr)
                elif isinstance(expr, Variable):
                    new_expr = BinaryOp('+', Variable(var), Number(0))  # Treat as no-op or reassign
                elif isinstance(expr, BinaryOp):
                    new_expr = expr
                if self.verbose:
                    expr_str = ""
                    if isinstance(new_expr, BinaryOp):
                        expr_str = f" with expression {new_expr.op}"
                    elif isinstance(new_expr, Number):
                        expr_str = f" with number value {new_expr.value}"
                    elif isinstance(new_expr, Variable):
                        expr_str = f" with variable {new_expr.name}"
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Parsed assignment to variable '{var}'{expr_str} at {token.line}:{token.column}")
                if self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'end of variable value assignment')
                return Assignment(var, new_expr)
            else:
                if self.peek() and self.peek().type == '\n':
                    self.consume('\n', 'end of variable value assignment')
                if self.verbose:
                    expr_str = ""
                    if isinstance(expr, StringLiteral):
                        expr_str = f" with string value '{expr.value}'"
                    print(f"ildzc[parser:{inspect.currentframe().f_lineno}] Parsed assignment to variable '{var}'{expr_str} at {token.line}:{token.column}")
                return Assignment(var, expr)
        elif self.peek().type == 'SINGLE_QUOTE':
            self.consume('SINGLE_QUOTE', 'end of if statement block')
            if self.peek() and self.peek().type == '\n':
                self.consume('\n', 'end of if statement block')
            return None
        token = self.peek() if self.peek() else Token('EOF', 'EOF', -1, -1)
        expected = ", ".join(sorted(keywords))
        raise SyntaxError(
            f"ildzc[parser:{inspect.currentframe().f_lineno}] Unexpected {token.type} '{token.value}' "
            f"at {token.line}:{token.column}. Expected one of: {expected}"
        )

    def parse(self) -> List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall]]:
        program = []
        while self.peek() is not None:
            if self.peek().type == '\n':
                self.consume('\n', 'generic context')
                continue
            stmt = self.parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    program.extend(stmt)
                else:
                    program.append(stmt)

        # Validate function calls after parsing all definitions
        for call in self.function_calls:
            if call.name not in self.functions:
                raise SyntaxError(f"ildzc[parser:{inspect.currentframe().f_lineno}] Call at {call.line}:1 to undefined function '{call.name}'")
            # Check argument count
            func_def = self.functions[call.name]
            if len(call.args) != len(func_def.params):
                expected_count = len(func_def.params)
                got_count = len(call.args)
                arg_word = "argument" if expected_count == 1 else "arguments"

                # Build a list of "type name" strings for expected parameters
                typed_params = [f"{typ} {name}" for typ, name in zip(func_def.param_types, func_def.params)]

                typed_params_str = ", ".join(typed_params)

                raise SyntaxError(
                    f"ildzc[parser:{inspect.currentframe().f_lineno}] Call at {call.line}:1 to function '{call.name}' "
                    f"defined at {func_def.line}:2 expects {expected_count} {arg_word} ([type, name] {typed_params_str}), but got {got_count}"
                )

        # Filter out uncalled function definitions
        filtered_program = []
        for stmt in program:
            if isinstance(stmt, FunctionDefinition):
                if stmt.name in self.called_functions:
                    filtered_program.append(stmt)
            else:
                filtered_program.append(stmt)

        if self.verbose:
            print(f"\033[92m[SUCCESS] ildzc[parser:{inspect.currentframe().f_lineno}] Completed parsing program with {len(filtered_program)} statements\033[0m\n")
        return filtered_program

# Optimization: Constant Folding
def optimize(ast: List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall]], verbose: bool = False) -> List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall]]:
    def fold(expr: Union[Number, Variable, BinaryOp, StringLiteral]) -> Union[Number, Variable, BinaryOp, StringLiteral]:
        if isinstance(expr, BinaryOp):
            left = fold(expr.left)
            right = fold(expr.right)
            if isinstance(left, Number) and isinstance(right, Number):
                if verbose:
                    print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Folding constant expression: {left.value} {expr.op} {right.value}")
                if expr.op == '+':
                    result = Number(left.value + right.value)
                    if verbose:
                        print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Result: {result.value}")
                    return result
                elif expr.op == '-':
                    result = Number(left.value - right.value)
                    if verbose:
                        print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Result: {result.value}")
                    return result
                elif expr.op == '*':
                    result = Number(left.value * right.value)
                    if verbose:
                        print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Result: {result.value}")
                    return result
                elif expr.op == '/':
                    result = Number(left.value / right.value)
                    if verbose:
                        print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Result: {result.value}")
                    return result
                elif expr.op in ('>', '<', 'GE', 'LE', 'EQ', 'NE'):
                    if expr.op == '>':
                        result = Number(1 if left.value > right.value else 0)
                    elif expr.op == '<':
                        result = Number(1 if left.value < right.value else 0)
                    elif expr.op == 'GE':
                        result = Number(1 if left.value >= right.value else 0)
                    elif expr.op == 'LE':
                        result = Number(1 if left.value <= right.value else 0)
                    elif expr.op == 'EQ':
                        result = Number(1 if left.value == right.value else 0)
                    elif expr.op == 'NE':
                        result = Number(1 if left.value != right.value else 0)
                    if verbose:
                        print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Result: {result.value}")
                    return result
            return BinaryOp(expr.op, left, right)
        return expr

    optimized = []
    for stmt in ast:
        if isinstance(stmt, Assignment):
            optimized_expr = fold(stmt.expr)
            optimized.append(Assignment(stmt.var, optimized_expr))
            if verbose and isinstance(optimized_expr, Number):
                print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Optimized assignment to '{stmt.var}' with constant value {optimized_expr.value}")
        elif isinstance(stmt, IfStatement):
            optimized_condition = fold(stmt.condition)
            if verbose and isinstance(optimized_condition, Number):
                print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Optimized if condition to constant value {optimized_condition.value}")
            optimized_then = []
            for s in stmt.then_block:
                if isinstance(s, Assignment):
                    optimized_then.append(Assignment(s.var, fold(s.expr)))
                elif isinstance(s, IfStatement):
                    optimized_nested_then = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.then_block]
                    optimized_nested_else = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.else_block] if s.else_block else None
                    optimized_then.append(IfStatement(fold(s.condition), optimized_nested_then, s.line, optimized_nested_else))
                else:
                    optimized_then.append(s)
            optimized_else = None
            if stmt.else_block:
                optimized_else = []
                for s in stmt.else_block:
                    if isinstance(s, Assignment):
                        optimized_else.append(Assignment(s.var, fold(s.expr)))
                    elif isinstance(s, IfStatement):
                        optimized_nested_then = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.then_block]
                        optimized_nested_else = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.else_block] if s.else_block else None
                        optimized_else.append(IfStatement(fold(s.condition), optimized_nested_then, s.line, optimized_nested_else))
                    else:
                        optimized_else.append(s)
            optimized.append(IfStatement(optimized_condition, optimized_then, stmt.line, optimized_else))
        elif isinstance(stmt, Declaration) and stmt.value is not None:
            optimized_value = fold(stmt.value)
            optimized.append(Declaration(stmt.var, stmt.type_name, optimized_value))
            if verbose and isinstance(optimized_value, Number):
                print(f"ildzc[optimizer:{inspect.currentframe().f_lineno}] Optimized declaration of '{stmt.var}' with constant value {optimized_value.value}")
        elif isinstance(stmt, FunctionDefinition):
            optimized_body = []
            for s in stmt.body:
                if isinstance(s, Assignment):
                    optimized_body.append(Assignment(s.var, fold(s.expr)))
                elif isinstance(s, IfStatement):
                    optimized_then = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.then_block]
                    optimized_else = [Assignment(t.var, fold(t.expr)) if isinstance(t, Assignment) else t for t in s.else_block] if s.else_block else None
                    optimized_body.append(IfStatement(fold(s.condition), optimized_then, s.line, optimized_else))
                else:
                    optimized_body.append(s)
            optimized.append(FunctionDefinition(stmt.name, stmt.params, stmt.param_types, optimized_body, stmt.line))
        else:
            optimized.append(stmt)
    if verbose:
        print(f"\033[92m[SUCCESS] ildzc[optimizer:{inspect.currentframe().f_lineno}] Completed optimization of {len(ast)} statements\033[0m\n")
    return optimized

def create_num_lookup_table():
    with open('num_lookup_table.bin', 'wb') as f:
        for i in range(10000):
            f.write(f"{i:04d}".encode('ascii'))

class FunctionContext:
    """Manages stack offsets and variable mappings for a function or inlining scope."""
    def __init__(self, parent_offset: int = 32):
        self.var_map: Dict[str, int] = {}
        self.var_types: Dict[str, str] = {}
        self.stack_offset: int = parent_offset
    
    def add_variable(self, var: str, type_name: str) -> int:
        """Add a variable to the context and return its stack offset."""
        offset = self.stack_offset
        self.var_map[var] = offset
        self.var_types[var] = type_name
        self.stack_offset += 8
        return offset

global_context = FunctionContext(32)  # Global scope starts at offset 32
global_context.add_variable("console_handle", "number")  # Offset 32
global_context.add_variable("__saved_rbx", "number")     # Offset 40
global_context.add_variable("output_buffer_ptr", "number")  # Offset 48

def generate_assembly(ast: List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall, LoopStatement, BreakStatement]], output_file: str, input_file: str):
    create_num_lookup_table()
    if verbose_generator:
        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Starting assembly generation\033[0m")
    CONSOLE_SLOT = 16
    SAVED_RBX_SLOT = 24

    data_section = [
        "default rel",
        "global Start",
        "extern ExitProcess",
        "extern GetStdHandle",
        "extern ReadFile",
        "extern WriteFile",
        "extern CreateFileA",
        "extern CloseHandle",
        "extern GetLastError",
        "extern AddVectoredExceptionHandler",
        "\nsection .data",
        "empty_string db 0",
        "int_to_str_buffer db 20 dup(0) ; Buffer for number-to-string conversion",
        "output_buffer db 4096 dup(0) ; Large static output buffer for batching prints",
        "newline db 13, 10, 0, 0 ; CRLF for console output",
        "bytes_written dd 0",
        "is_file db 0",
        "debug_log db 'debug.log',0",
        "ex_msg db 'Exception code: ',0",
        "wf_error db 'WriteFile failed with code: ',0",
        "debug_start db 'Program started',13,10,0",
        "debug_handle db 'Console handle: ',0",
        "debug_stack db 'Stack space: ',0",
        "debug_offsets db 'Variable offsets:',13,10,0",
        "num_lookup_table:",
        "incbin 'num_lookup_table.bin'"
    ]
    text_section = [
        "; Text section: code and functions",
        "section .text"
    ]
    init_after_prologue = []
    string_map = {}
    string_count = 0
    label_map = {}
    label_count = 0

    # Set up global_context variables
    global_context.var_map["console_handle"] = CONSOLE_SLOT
    global_context.var_types["console_handle"] = "number"
    global_context.var_map["__saved_rbx"] = SAVED_RBX_SLOT
    global_context.var_types["__saved_rbx"] = "number"
    global_context.var_types["output_buffer_ptr"] = "number"

    def create_label(prefix: str, source_line: int) -> str:
        nonlocal label_count
        label = f"{prefix}_{label_count}"
        label_map[label] = f"{input_file}[{source_line}]"
        label_count += 1
        return label

    def should_inline(func: FunctionDefinition) -> bool:
        """Determine if a function should be inlined based on body size."""
        return len(func.body) <= 10

    def count_variables(stmts: List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall, LoopStatement, BreakStatement]], context: FunctionContext):
        """Count variables to determine stack space requirements."""
        for stmt in stmts:
            if isinstance(stmt, Declaration):
                offset = context.add_variable(stmt.var, stmt.type_name)
                if verbose_generator:
                    print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added variable {stmt.var} of type {stmt.type_name} at offset {offset}\033[0m")
            elif isinstance(stmt, IfStatement):
                count_variables(stmt.then_block, context)
                if stmt.else_block:
                    count_variables(stmt.else_block, context)
            elif isinstance(stmt, FunctionDefinition):
                count_variables(stmt.body, context)
            elif isinstance(stmt, LoopStatement):
                offset = context.add_variable(f"loop_counter_{stmt.line}", "number")
                if verbose_generator:
                    print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added loop counter at line {stmt.line} at offset {offset}\033[0m")
                count_variables(stmt.body, context)

    def num_to_str_asm():
        """Generate assembly for number-to-string conversion and printing."""
        return [
            "; Convert number in rax to string and print it",
            "num_to_str:",
            "    mov rcx, rax                  ; Save input for sign check",
            "    test rax, rax",
            "    jns .skip_neg",
            "    neg rax                       ; Handle negative numbers",
            ".skip_neg:",
            "    cmp rax, 9999",
            "    ja .long_path                 ; Numbers > 9999 use slow path",
            "    lea rsi, [num_lookup_table + rax*4] ; Index into lookup table",
            "    mov rax, rsi",
            "    test rcx, rcx",
            "    jns .ret_val",
            "    dec rsi",
            "    mov byte [rsi], '-'           ; Add negative sign",
            "    mov rax, rsi",
            "    ret",
            ".long_path:",
            "    lea rsi, [rel int_to_str_buffer + 19] ; Buffer for large numbers",
            "    mov rbx, 10",
            ".loop:",
            "    mov rdx, rax",
            "    imul rdx, -858993459          ; Magic divide by 10",
            "    shr rdx, 35",
            "    lea r8, [rdx*4 + rdx]",
            "    shl r8, 1",
            "    mov r9, rax",
            "    sub r9, r8",
            "    add r9b, '0'                  ; Convert digit to ASCII",
            "    dec rsi",
            "    mov [rsi], r9b",
            "    mov rax, rdx",
            "    test rax, rax",
            "    jnz .loop",
            "    lea rdx, [rel int_to_str_buffer + 19] ; Check if no digits (for 0)",
            "    cmp rsi, rdx",
            "    jne .check_sign",
            "    mov byte [rsi], '0'",
            ".check_sign:",
            "    test rcx, rcx",
            "    jns .skip_sign",
            "    dec rsi",
            "    mov byte [rsi], '-'           ; Add negative sign for large numbers",
            ".skip_sign:",
            "    mov rax, rsi",
            ".ret_val:",
            "    ret",
            "; Print number from rax",
            "print_number:",
            f"    mov [rsp + {global_context.var_map['__saved_rbx']}], rbx ; Save rbx",
            "    call num_to_str               ; Convert number to string",
            "    mov rbx, rax                  ; Store string pointer",
            "    lea rdx, [rel num_lookup_table]",
            "    lea rcx, [rel num_lookup_table + 40000] ; 10000*4",
            "    cmp rbx, rdx",
            "    jb .varlen_print",
            "    cmp rbx, rcx",
            "    jae .varlen_print",
            "    mov rsi, rbx",
            "    lea rdi, [rel int_to_str_buffer + 16] ; Copy to buffer",
            "    mov rcx, 4",
            "    cld",
            "    rep movsb",
            "    xor rdx, rdx                  ; Index for trimming",
            "    mov r8d, 4",
            ".fast_trim_loop:",
            "    mov al, [rdi + rdx]",
            "    cmp al, '0'",
            "    jne .fast_trim_found",
            "    inc rdx",
            "    dec r8d",
            "    cmp rdx, 4",
            "    jne .fast_trim_loop",
            "    lea rdx, [rel int_to_str_buffer + 19] ; Single '0' case",
            "    mov r8d, 1",
            "    jmp .do_write",
            ".fast_trim_found:",
            "    lea rax, [rel int_to_str_buffer + 16]",
            "    add rax, rdx",
            "    mov rdx, rax",
            "    jmp .do_write",
            ".varlen_print:",
            "    lea rax, [rel int_to_str_buffer + 20] ; End of buffer",
            "    mov r8, rax",
            "    sub r8, rbx                   ; Calculate length",
            "    mov rdx, rbx                  ; Pointer to string",
            ".do_write:",
            "    call append_string            ; Append to buffer",
            f"    mov rbx, [rsp + {global_context.var_map['__saved_rbx']}] ; Restore rbx",
            "    ret"
        ]

    def collect_strings_and_vars(stmts: List[Union[Assignment, Declaration, IfStatement, Print, FunctionDefinition, FunctionCall, LoopStatement, BreakStatement]], context: FunctionContext):
        """Collect string literals and variable declarations."""
        nonlocal string_count
        for stmt in stmts:
            if isinstance(stmt, Declaration):
                offset = context.var_map[stmt.var]  # Already added in count_variables
                if stmt.type_name == 'string':
                    if stmt.value is None:
                        data_section.append(f"string_{stmt.var} dq empty_string")
                        init_after_prologue.append(f"    ; Initialize string variable {stmt.var}")
                        init_after_prologue.append(f"    lea rax, [rel empty_string]")
                        init_after_prologue.append(f"    mov [rsp + {offset}], rax")
                    else:
                        data_section.append(f"string_{stmt.var} dq 0 ; Pointer set at runtime")
                    if stmt.value is not None:
                        if isinstance(stmt.value, StringLiteral):
                            string_value = stmt.value.value
                            if string_value not in string_map:
                                string_map[string_value] = f"str_{string_count}"
                                data_section.append(f"{string_map[string_value]} db {nasm_string_literal(string_value)}, 0")
                                string_count += 1
                                if verbose_generator:
                                    print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added string literal '{string_value}' as {string_map[string_value]}\033[0m")
                            init_after_prologue.append(f"    ; Set string {stmt.var} to '{string_value}'")
                            init_after_prologue.append(f"    lea rax, [rel {string_map[string_value]}]")
                            init_after_prologue.append(f"    mov [rsp + {offset}], rax")
                        else:
                            raise ValueError(f"Invalid value type for string variable '{stmt.var}': {type(stmt.value)}")
                elif stmt.type_name == 'number':
                    if stmt.value is None:
                        init_after_prologue.append(f"    ; Initialize number variable {stmt.var} to 0")
                        init_after_prologue.append(f"    mov qword [rsp + {offset}], 0")
                    elif isinstance(stmt.value, Number):
                        init_after_prologue.append(f"    ; Initialize number variable {stmt.var} to {stmt.value.value}")
                        init_after_prologue.append(f"    mov qword [rsp + {offset}], {int(stmt.value.value)}")
                    elif isinstance(stmt.value, BinaryOp):
                        init_after_prologue.extend(gen_expr(stmt.value, "rax", dest_var=stmt.var, context=context))
                        init_after_prologue.append(f"    mov [rsp + {offset}], rax ; Store result")
                    else:
                        raise ValueError(f"Invalid value type for number variable '{stmt.var}': {type(stmt.value)}")
            elif isinstance(stmt, Assignment) and isinstance(stmt.expr, StringLiteral):
                string_value = stmt.expr.value
                if string_value not in string_map:
                    string_map[string_value] = f"str_{string_count}"
                    data_section.append(f"{string_map[string_value]} db {nasm_string_literal(string_value)}, 0")
                    string_count += 1
                    if verbose_generator:
                        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added string literal '{string_value}' as {string_map[string_value]} for assignment\033[0m")
                    init_after_prologue.append(f"    ; Assign string '{string_value}' to {stmt.var}")
                    init_after_prologue.append(f"    lea rax, [rel {string_map[string_value]}]")
                    init_after_prologue.append(f"    mov [rsp + {context.var_map[stmt.var]}], rax")
            elif isinstance(stmt, Print):
                prefix = f"{input_file}[{stmt.line}] "
                if isinstance(stmt.arg, StringLiteral):
                    combined_str = f"{prefix}{stmt.arg.value}"
                    if combined_str not in string_map:
                        string_map[combined_str] = f"str_{string_count}"
                        data_section.append(f"{string_map[combined_str]} db {nasm_string_literal(combined_str)}, 0")
                        string_count += 1
                        if verbose_generator:
                            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added combined string '{combined_str}' as {string_map[combined_str]} for print\033[0m")
                elif isinstance(stmt.arg, Variable) and context.var_types.get(stmt.arg.name) != 'string':
                    if prefix not in string_map:
                        string_map[prefix] = f"prefix_{string_count}"
                        data_section.append(f"{string_map[prefix]} db {nasm_string_literal(prefix)}, 0")
                        string_count += 1
                        if verbose_generator:
                            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added prefix '{prefix}' as {string_map[prefix]} for print\033[0m")
                    formatted_str = f"{stmt.arg.name} = "
                    if formatted_str not in string_map:
                        string_map[formatted_str] = f"str_{string_count}"
                        data_section.append(f"{string_map[formatted_str]} db {nasm_string_literal(formatted_str)}, 0")
                        string_count += 1
                        if verbose_generator:
                            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added formatted string '{formatted_str}' as {string_map[formatted_str]} for print\033[0m")
            elif isinstance(stmt, IfStatement):
                collect_strings_and_vars(stmt.then_block, context)
                if stmt.else_block:
                    collect_strings_and_vars(stmt.else_block, context)
            elif isinstance(stmt, FunctionDefinition):
                collect_strings_and_vars(stmt.body, context)
            elif isinstance(stmt, LoopStatement):
                collect_strings_and_vars(stmt.body, context)

    def gen_return(stmt: ReturnStatement, func_def: Optional[FunctionDefinition], inlined: bool, context: FunctionContext) -> List[str]:
        """Generate assembly for return statements."""
        lines = [f"; Return statement at {input_file}[0]"]
        func_name = func_def.name if func_def else "None"
        if verbose_generator:
            if inlined:
                print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating inlined return for function '{func_name}'\033[0m")
            else:
                print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating return for function '{func_name}'\033[0m")
        if inlined:
            if stmt.value is not None:
                lines += gen_expr(stmt.value, "rax", context=context)
            return lines
        if stmt.value is None:
            lines.append("    ret")
        else:
            lines.extend(gen_expr(stmt.value, "rax", context=context))
            lines.append("    ret")
        return lines

    def gen_expr(expr: Union[Number, Variable, BinaryOp, StringLiteral], reg: str, dest_var: str = None, context: FunctionContext = global_context) -> List[str]:
        """Generate assembly for expressions."""
        lines = [f"; Evaluate expression for {dest_var if dest_var else reg}"]
        if verbose_generator:
            expr_type = type(expr).__name__
            op = getattr(expr, 'op', None)
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating expression {expr_type} {op if op else ''} for {dest_var if dest_var else reg}\033[0m")
        if isinstance(expr, StringLiteral) and dest_var:
            string_label = string_map.get(expr.value)
            if not string_label:
                nonlocal string_count
                string_label = f"str_{string_count}"
                string_map[expr.value] = string_label
                data_section.append(f"{string_label} db {nasm_string_literal(expr.value)}, 0")
                string_count += 1
                if verbose_generator:
                    print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added runtime string literal '{expr.value}' as {string_label}\033[0m")
            return [
                f"    ; Store string literal '{expr.value}' to {dest_var}",
                f"    lea rax, [rel {string_label}]",
                f"    mov [rsp + {context.var_map[dest_var]}], rax"
            ]
        elif isinstance(expr, Number) and dest_var:
            return [
                f"    ; Store number {expr.value} to {dest_var}",
                f"    mov qword [rsp + {context.var_map[dest_var]}], {int(expr.value)}"
            ]
        elif isinstance(expr, Variable) and dest_var:
            return [
                f"    ; Copy variable {expr.name} to {dest_var}",
                f"    mov rax, [rsp + {context.var_map[expr.name]}]",
                f"    mov [rsp + {context.var_map[dest_var]}], rax"
            ]
        elif isinstance(expr, Variable):
            return [f"    mov {reg}, [rsp + {context.var_map[expr.name]}]"]
        elif isinstance(expr, BinaryOp):
            if dest_var and isinstance(expr.left, Variable) and expr.left.name == dest_var and isinstance(expr.right, Number) and expr.right.value == 1:
                if expr.op == '+':
                    return [f"    ; Increment {dest_var}", f"    inc qword [rsp + {context.var_map[dest_var]}]"]
                elif expr.op == '-':
                    return [f"    ; Decrement {dest_var}", f"    dec qword [rsp + {context.var_map[dest_var]}]"]
            lines += gen_expr(expr.left, "rax", context=context)
            if isinstance(expr.right, Number) and expr.op in ('+', '-', '*'):
                value = int(expr.right.value)
                if expr.op == '+':
                    lines.append(f"    add rax, {value} ; Add {value}")
                elif expr.op == '-':
                    lines.append(f"    sub rax, {value} ; Subtract {value}")
                elif expr.op == '*':
                    lines.append(f"    imul rax, {value} ; Multiply by {value}")
                if dest_var:
                    lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
            elif isinstance(expr.right, Number) and expr.op == '/':
                lines += gen_expr(expr.left, "rax", context=context)
                lines.append(f"    mov rbx, {int(expr.right.value)} ; Divisor")
                lines.append("    call fast_divide_by_cached ; Divide rax by rbx")
                if dest_var:
                    lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store quotient")
            elif expr.op in ('>', '<', 'GE', 'LE', 'EQ', 'NE') and isinstance(expr.right, Variable) and dest_var:
                lines.append(f"    cmp rax, [rsp + {context.var_map[expr.right.name]}] ; Compare with {expr.right.name}")
                if expr.op == '>': lines.append("    setg al")
                elif expr.op == '<': lines.append("    setl al")
                elif expr.op == 'GE': lines.append("    setge al")
                elif expr.op == 'LE': lines.append("    setle al")
                elif expr.op == 'EQ': lines.append("    sete al")
                elif expr.op == 'NE': lines.append("    setne al")
                lines.append("    movzx rax, al ; Extend boolean result")
                if dest_var:
                    lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
            else:
                lines += gen_expr(expr.right, "rbx", context=context)
                if expr.op == '+':
                    lines.append("    add rax, rbx ; Add operands")
                    if dest_var:
                        lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
                elif expr.op == '-':
                    lines.append("    sub rax, rbx ; Subtract operands")
                    if dest_var:
                        lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
                elif expr.op == '*':
                    lines.append("    imul rax, rbx ; Multiply operands")
                    if dest_var:
                        lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
                elif expr.op == '/':
                    lines.append("    call fast_divide_by_cached ; Divide rax by rbx")
                    if dest_var:
                        lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store quotient")
                elif expr.op in ('>', '<', 'GE', 'LE', 'EQ', 'NE'):
                    lines.append("    cmp rax, rbx ; Compare operands")
                    if expr.op == '>': lines.append("    setg al")
                    elif expr.op == '<': lines.append("    setl al")
                    elif expr.op == 'GE': lines.append("    setge al")
                    elif expr.op == 'LE': lines.append("    setle al")
                    elif expr.op == 'EQ': lines.append("    sete al")
                    elif expr.op == 'NE': lines.append("    setne al")
                    lines.append("    movzx rax, al ; Extend boolean result")
                    if dest_var:
                        lines.append(f"    mov [rsp + {context.var_map[dest_var]}], rax ; Store result")
            return lines
        return lines

    def get_or_add_string(s: str) -> str:
        """Get or add a string to the data section."""
        nonlocal string_count
        if s not in string_map:
            string_map[s] = f"str_{string_count}"
            data_section.append(f"{string_map[s]} db {nasm_string_literal(s)}, 0")
            string_count += 1
            if verbose_generator:
                print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Added string '{s}' as {string_map[s]}\033[0m")
        return string_map[s]

    def gen_call(func_name: str, num_params: int = 1, has_overlapped: bool = False) -> List[str]:
        space = 32 + ((num_params - 4) * 8 if num_params > 4 else 0)
        lines = [f"    sub rsp, {space}"]
        if has_overlapped:
            lines.append("    mov qword [rsp + 32], 0")
        lines.append(f"    call {func_name}")
        lines.append(f"    add rsp, {space}")
        return lines

    def append_string_asm() -> List[str]:
        ptr_offset = global_context.var_map["output_buffer_ptr"]  # Use 48
        return [
            "append_string:",
            f"    mov rdi, [rsp + {ptr_offset}] ; load ptr",
            "    mov rax, rdi",
            "    sub rax, [rel output_buffer]",
            "    add rax, r8 ; future size",
            "    cmp rax, 4096",
            "    jbe .append",
            "    call flush_buffer",
            f"    mov rdi, [rsp + {ptr_offset}] ; reload ptr",
            ".append:",
            "    mov rsi, rdx ; string",
            "    mov rcx, r8 ; length",
            "    cld",
            "    rep movsb",
            f"    mov [rsp + {ptr_offset}], rdi ; update ptr",
            "    ret"
        ]

    def exception_handler_asm():
        return [
            "ExceptionHandler:",
            "    sub rsp, 40",
            "    mov [rsp + 32], rcx ; PEXCEPTION_POINTERS",
            "    lea rdx, [rel ex_msg]",
            "    mov r8, 16",
            "    call append_string",
            "    mov rcx, [rsp + 32]",
            "    mov rcx, [rcx] ; ExceptionRecord",
            "    mov rax, [rcx] ; ExceptionCode",
            "    call print_number",
            "    lea rdx, [rel newline]",
            "    mov r8, 2",
            "    call append_string",
            "    call flush_buffer",
            "    cmp byte [rel is_file], 0",
            "    jne .exit",
            "    lea rcx, [rel debug_log]",
            "    mov rdx, 0x40000000 ; GENERIC_WRITE",
            "    xor r8, r8",
            "    xor r9, r9",
            "    sub rsp, 56",
            "    mov qword [rsp + 32], 2 ; CREATE_ALWAYS",
            "    mov qword [rsp + 40], 0x80 ; FILE_ATTRIBUTE_NORMAL",
            "    mov qword [rsp + 48], 0",
            "    call CreateFileA",
            "    add rsp, 56",
            "    cmp rax, -1",
            "    je .exit",
            f"    mov [rsp + {global_context.var_map['console_handle']}], rax",
            "    mov byte [rel is_file], 1",
            "    call flush_buffer",
            ".exit:",
            "    mov rax, -1 ; EXCEPTION_CONTINUE_SEARCH",
            "    add rsp, 40",
            "    ret"
        ]

    def flush_buffer_asm():
        console_offset = global_context.var_map["console_handle"]
        ptr_offset = global_context.var_map["output_buffer_ptr"]  # Use 48
        return [
            "flush_buffer:",
            f"    mov rcx, [rsp + {console_offset}] ; handle",
            "    lea rdx, [rel output_buffer] ; buffer",
            f"    mov r8, [rsp + {ptr_offset}] ; ptr",
            "    sub r8, rdx ; length",
            "    test r8, r8",
            "    jz .no_flush",
            "    lea r9, [rel bytes_written] ; &bytes_written",
            "    sub rsp, 40",
            "    mov qword [rsp + 32], 0",
            "    call WriteFile",
            "    add rsp, 40",
            "    test rax, rax",
            "    jnz .flush_done",
            "    call GetLastError",
            "    mov rbx, rax ; save error",
            "    cmp byte [rel is_file], 1",
            "    je .try_new_file",
            "    lea rcx, [rel debug_log]",
            "    mov rdx, 0x40000000 ; GENERIC_WRITE",
            "    xor r8, r8",
            "    xor r9, r9",
            "    sub rsp, 56",
            "    mov qword [rsp + 32], 2 ; CREATE_ALWAYS",
            "    mov qword [rsp + 40], 0x80 ; FILE_ATTRIBUTE_NORMAL",
            "    mov qword [rsp + 48], 0",
            "    call CreateFileA",
            "    add rsp, 56",
            "    cmp rax, -1",
            "    je .failure_exit",
            f"    mov [rsp + {console_offset}], rax",
            "    mov byte [rel is_file], 1",
            ".retry_write:",
            f"    mov rdi, [rsp + {ptr_offset}] ; Load destination buffer ptr",
            "    lea rdx, [rel wf_error]",
            "    mov r8, 28",
            "    call append_string",
            f"    add qword [rsp + {ptr_offset}], r8 ; Update output buffer ptr",
            "    mov rax, rbx",
            "    call print_number",
            f"    mov rdi, [rsp + {ptr_offset}] ; Load destination buffer ptr",
            "    lea rdx, [rel newline]",
            "    mov r8, 2",
            "    call append_string",
            f"    add qword [rsp + {ptr_offset}], r8 ; Update output buffer ptr",
            f"    mov rcx, [rsp + {console_offset}]",
            "    lea rdx, [rel output_buffer]",
            f"    mov r8, [rsp + {ptr_offset}]",
            "    sub r8, rdx",
            "    lea r9, [rel bytes_written]",
            "    sub rsp, 40",
            "    mov qword [rsp + 32], 0",
            "    call WriteFile",
            "    add rsp, 40",
            "    test rax, rax",
            "    jnz .flush_done",
            "    call GetLastError",
            "    mov rbx, rax",
            ".try_new_file:",
            "    lea rcx, [rel debug_log]",
            "    mov rdx, 0x40000000 ; GENERIC_WRITE",
            "    xor r8, r8",
            "    xor r9, r9",
            "    sub rsp, 56",
            "    mov qword [rsp + 32], 2 ; CREATE_ALWAYS",
            "    mov qword [rsp + 40], 0x80 ; FILE_ATTRIBUTE_NORMAL",
            "    mov qword [rsp + 48], 0",
            "    call CreateFileA",
            "    add rsp, 56",
            "    cmp rax, -1",
            "    je .failure_exit",
            f"    mov rcx, [rsp + {console_offset}] ; Close old handle",
            "    sub rsp, 32",
            "    call CloseHandle",
            "    add rsp, 32",
            f"    mov [rsp + {console_offset}], rax ; Store new handle",
            "    mov byte [rel is_file], 1",
            "    jmp .retry_write",
            ".flush_done:",
            "    lea rax, [rel output_buffer]",
            f"    mov [rsp + {ptr_offset}], rax ; reset ptr",
            ".no_flush:",
            "    ret",
            ".failure_exit:",
            "    mov rcx, rbx",
            "    sub rsp, 32",
            "    call ExitProcess"
        ]
    def asm_strlen_from_var(var: str, context: FunctionContext) -> List[str]:
        """Generate assembly to compute string length from a variable."""
        strlen_label = create_label("strlen", 0)
        strlen_done_label = create_label("strlen_done", 0)
        return [
            f"; Compute length of string in variable {var}",
            f"    mov rsi, [rsp + {context.var_map[var]}] ; Load string pointer",
            "    xor r8, r8 ; Initialize length counter",
            f"{strlen_label}: ; {label_map[strlen_label]}",
            "    cmp byte [rsi + r8], 0 ; Check for null terminator",
            f"    je {strlen_done_label}",
            "    inc r8 ; Increment length",
            f"    jmp {strlen_label}",
            f"{strlen_done_label}: ; {label_map[strlen_done_label]}"
        ]

    def gen_print(stmt: Print, context: FunctionContext) -> List[str]:
        if verbose_generator:
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating print statement at line {stmt.line}\033[0m")
        lines = [f"; Print statement at {input_file}[{stmt.line}]"]
        prefix = f"{input_file}[{stmt.line}] "
        prefix_label = get_or_add_string(prefix)
        lines += [
            "; Append prefix",
            f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
            f"    lea rdx, [{prefix_label}]",
            f"    mov r8, {len(prefix)}",
            "    call append_string",
            f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr"
        ]
        
        if isinstance(stmt.arg, StringLiteral):
            label = get_or_add_string(stmt.arg.value)
            lines += [
                "; Append string literal",
                f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
                f"    lea rdx, [{label}]",
                f"    mov r8, {len(stmt.arg.value)}",
                "    call append_string",
                f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr"
            ]
        elif isinstance(stmt.arg, Variable):
            if context.var_types.get(stmt.arg.name) == 'string':
                lines += asm_strlen_from_var(stmt.arg.name, context)
                lines += [
                    "; Append string variable",
                    f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
                    "    mov rdx, rsi ; String pointer",
                    "    mov r8, r8 ; Length",
                    "    call append_string",
                    f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr"
                ]
            else:
                lines += [
                    "; Append formatted",
                    f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
                    f"    lea rdx, [str_{stmt.arg.name}]",
                    f"    mov r8, {len(stmt.arg.name) + 3}",
                    "    call append_string",
                    f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr",
                    f"    mov rax, [rsp + {context.var_map[stmt.arg.name]}]",
                    "    call print_number ; Append number value"
                ]
        # Append newline
        lines += [
            "; Append newline",
            f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
            "    lea rdx, [rel newline]",
            "    mov r8, 2",
            "    call append_string",
            f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr"
        ]
        return lines

    def gen_error(stmt: Print) -> List[str]:
        """Generate assembly for error printing with non-zero exit."""
        if verbose_generator:
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating error print at line {stmt.line}\033[0m")
        return [
            f"; Error at {input_file}[{stmt.line}]",
            *gen_print(stmt, global_context),
            "    call flush_buffer",
            *emit_exit(1)  # Use non-zero exit code for errors
        ]

def gen_block(
    stmts: List[Union[Assignment, IfStatement, Print, FunctionCall, ReturnStatement, LoopStatement, BreakStatement]],
    label_prefix: str,
    source_line: int,
    *,
    func_def: Optional[FunctionDefinition] = None,
    inlined: bool = False,
    inlining_stack: Optional[Set[str]] = None,
    context: FunctionContext = global_context
) -> List[str]:
    lines = [f"; Block at {input_file}[{source_line}]"]
    if inlining_stack is None:
        inlining_stack = set()
    
    for stmt in stmts:
        if verbose_generator:
            stmt_type = type(stmt).__name__
            line = getattr(stmt, 'line', source_line)
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating {stmt_type} at {input_file}[{line}]\033[0m")
        if isinstance(stmt, ReturnStatement):
            lines += gen_return(stmt, func_def, inlined, context)
            if inlined and stmt.value is not None:
                lines.append("; Propagate return value for inlined function")
                lines += gen_expr(stmt.value, "rax", context=context)
        elif isinstance(stmt, FunctionCall):
            func_def_call = next((f for f in ast if isinstance(f, FunctionDefinition) and f.name == stmt.name), None)
            if func_def_call and should_inline(func_def_call) and func_def_call.name not in inlining_stack:
                lines.append(f"; Inline function {stmt.name} at {input_file}[{stmt.line}]")
                new_context = FunctionContext(context.stack_offset)
                new_stack = inlining_stack | {func_def_call.name}
                for i, (arg, param) in enumerate(zip(stmt.args, func_def_call.params)):
                    offset = new_context.add_variable(param, 'number' if isinstance(arg, Number) else 'string')
                    lines += gen_arg_to_register_or_stack(arg, i, context, func_def_call)
                    lines.append(f"    mov [rsp + {offset}], {['rcx', 'rdx', 'r8', 'r9'][i if i < 4 else 0]} ; Store param {param}")
                lines += gen_block(func_def_call.body, f"inline_{stmt.name}", stmt.line, func_def=func_def_call, inlined=True, inlining_stack=new_stack, context=new_context)
            else:
                lines += gen_function_call(stmt, context, use_registers=True)
        elif isinstance(stmt, Assignment):
            lines += gen_expr(stmt.expr, "rax", dest_var=stmt.var, context=context)
        elif isinstance(stmt, Print):
            lines += gen_error(stmt) if stmt.is_error else gen_print(stmt, context, global_context)  # Pass global_context
            lines.append("    call flush_buffer ; Ensure immediate output")
        elif isinstance(stmt, IfStatement):
            line_num = stmt.line if isinstance(stmt.line, int) else source_line
            then_label = create_label(f"{label_prefix}_then", line_num)
            else_label = create_label(f"{label_prefix}_else", line_num)
            end_label = create_label(f"{label_prefix}_end", line_num)
            lines.append(f"; If statement at {input_file}[{line_num}]")
            if isinstance(stmt.condition, BinaryOp) and stmt.condition.op in ('>', '<', 'GE', 'LE', 'EQ', 'NE'):
                lines += gen_expr(stmt.condition.left, "rax", context=context)
                if isinstance(stmt.condition.right, Variable):
                    lines.append(f"    mov rbx, [rsp + {context.var_map[stmt.condition.right.name]}] ; Load {stmt.condition.right.name}")
                    lines.append(f"    cmp rax, rbx ; Compare with {stmt.condition.right.name}")
                elif isinstance(stmt.condition.right, Number):
                    lines.append(f"    mov rbx, {int(stmt.condition.right.value)} ; Load constant")
                    lines.append("    cmp rax, rbx ; Compare with constant")
                else:
                    lines += gen_expr(stmt.condition.right, "rbx", context=context)
                    lines.append("    cmp rax, rbx ; Compare operands")
                jump = {'>': 'jle', '<': 'jge', 'GE': 'jl', 'LE': 'jg', 'EQ': 'jne', 'NE': 'je'}[stmt.condition.op]
                lines.append(f"    {jump} {else_label if stmt.else_block else end_label}")
            else:
                lines += gen_expr(stmt.condition, "rax", context=context)
                lines.append("    test rax, rax ; Check condition")
                lines.append(f"    jz {else_label if stmt.else_block else end_label}")
            lines.append(f"{then_label}: ; {label_map[then_label]}")
            lines += gen_block(stmt.then_block, label_prefix, line_num, func_def=func_def, inlined=inlined, inlining_stack=inlining_stack.copy(), context=context)
            if stmt.else_block:
                lines.append(f"    jmp {end_label} ; Jump to end of if")
                lines.append(f"{else_label}: ; {label_map[else_label]}")
                lines += gen_block(stmt.else_block, label_prefix, line_num, func_def=func_def, inlined=inlined, inlining_stack=inlining_stack.copy(), context=context)
            lines.append(f"{end_label}: ; {label_map[end_label]}")
        elif isinstance(stmt, LoopStatement):
            loop_label = create_label(f"{label_prefix}_loop", stmt.line)
            end_label = create_label(f"{label_prefix}_loop_end", stmt.line)
            loop_counter = f"loop_counter_{stmt.line}"
            lines.append(f"; Loop at {input_file}[{stmt.line}]")
            lines += gen_expr(stmt.count, "rax", dest_var=loop_counter, context=context)
            lines.append(f"{loop_label}: ; {label_map[loop_label]}")
            lines.append(f"    mov rax, [rsp + {context.var_map[loop_counter]}] ; Load loop counter")
            lines.append("    test rax, rax ; Check if counter is zero")
            lines.append(f"    jz {end_label}")
            lines.append(f"    dec qword [rsp + {context.var_map[loop_counter]}] ; Decrement counter")
            lines += gen_block(stmt.body, f"{label_prefix}_loop_body", stmt.line, func_def=func_def, inlined=inlined, inlining_stack=inlining_stack.copy(), context=context)
            lines.append(f"    jmp {loop_label} ; Repeat loop")
            lines.append(f"{end_label}: ; {label_map[end_label]}")
        elif isinstance(stmt, BreakStatement):
            lines.append(f"; Break statement at {input_file}[{stmt.line}]")
            lines.append(f"    jmp {label_prefix}_loop_end ; Break to loop end")
    return lines

    def gen_arg_to_register_or_stack(arg: Union[Number, Variable, StringLiteral], index: int, context: FunctionContext, func_def: FunctionDefinition) -> List[str]:
        """Generate assembly to load argument into register or stack."""
        lines = [f"; Load argument {index} for function {func_def.name}"]
        if verbose_generator:
            arg_type = type(arg).__name__
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Loading arg {index} of type {arg_type} for {func_def.name}\033[0m")
        reg = ['rcx', 'rdx', 'r8', 'r9'][index] if index < 4 else None
        if isinstance(arg, Number):
            if reg:
                lines.append(f"    mov {reg}, {int(arg.value)} ; Load number")
            else:
                lines.append(f"    mov rax, {int(arg.value)}")
                lines.append(f"    mov [rsp + {32 + 8 * (index - 4)}], rax ; Store to stack")
        elif isinstance(arg, Variable):
            if reg:
                lines.append(f"    mov {reg}, [rsp + {context.var_map[arg.name]}] ; Load variable {arg.name}")
            else:
                lines.append(f"    mov rax, [rsp + {context.var_map[arg.name]}]")
                lines.append(f"    mov [rsp + {32 + 8 * (index - 4)}], rax ; Store to stack")
        elif isinstance(arg, StringLiteral):
            string_label = get_or_add_string(arg.value)
            if reg:
                lines.append(f"    lea {reg}, [rel {string_label}] ; Load string pointer")
            else:
                lines.append(f"    lea rax, [rel {string_label}]")
                lines.append(f"    mov [rsp + {32 + 8 * (index - 4)}], rax ; Store to stack")
        return lines

    def gen_function_call(stmt: FunctionCall, context: FunctionContext, use_registers: bool) -> List[str]:
        """Generate assembly for function calls, using registers or stack."""
        if verbose_generator:
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating function call to {stmt.name} at {input_file}[{stmt.line}]\033[0m")
        lines = [f"; Function call to {stmt.name} at {input_file}[{stmt.line}]"]
        num_args = len(stmt.args)
        space = 32 + ((num_args - 4) * 8 if num_args > 4 else 0)
        lines.append(f"    sub rsp, {space}")
        for i, arg in enumerate(stmt.args):
            lines += gen_arg_to_register_or_stack(arg, i, context, None)
        lines.append(f"    call {stmt.name} ; Call function")
        lines.append(f"    add rsp, {space} ; Restore stack")
        return lines

    def emit_exit(code: int) -> List[str]:
        return [
            f"    mov rcx, {code}",
            "    sub rsp, 32",
            "    call ExitProcess"
            # No add rsp, since ExitProcess doesn't return
        ]

    # Count variables and collect strings
    count_variables(ast, global_context)
    if verbose_generator:
        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Variables counted, stack_offset = {global_context.stack_offset}\033[0m")
    collect_strings_and_vars(ast, global_context)
    if verbose_generator:
        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Strings collected, count = {string_count}\033[0m")

    # Reserve scratch space for calls
    shadow_offset = global_context.stack_offset
    global_context.stack_offset += 40  # 32 shadow + 8 for potential 5th arg

    # Compute stack space (16-byte aligned)
    stack_space = ((global_context.stack_offset + 15) // 16) * 16
    if stack_space < 32:
        stack_space = 32
    if verbose_generator:
        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Computed stack space = {stack_space}\033[0m")

    # Add variable-specific debug strings
    var_debug_labels = {}
    for var, offset in global_context.var_map.items():
        if not var.startswith("__"):
            label = f"debug_var_{var}"
            data_section.append(f"{label} db '{var}: ',0")
            var_debug_labels[var] = label

    text_section += append_string_asm()
    text_section += flush_buffer_asm()
    text_section += num_to_str_asm()
    text_section += exception_handler_asm()
    text_section += [
        "; Program entry point",
        "Start:",
        f"    sub rsp, {stack_space} ; Allocate stack space",
        "    and rsp, -16 ; Align stack to 16 bytes",
        "; Initialize output buffer ptr",
        f"    lea rax, [rel output_buffer]",
        f"    mov [rsp + {global_context.var_map['output_buffer_ptr']}], rax ; Initialize output buffer ptr",
        "; Debug: Program started",
        f"    mov rdi, [rsp + {global_context.var_map['output_buffer_ptr']}] ; Load destination buffer ptr",
        "    lea rdx, [rel debug_start]",
        "    mov r8, 16 ; length of 'Program started\\r\\n'",
        "    call append_string",
        f"    add qword [rsp + {global_context.var_map['output_buffer_ptr']}], r8 ; Update output buffer ptr",
        "; Get console handle",
        "    mov rcx, -11 ; STD_OUTPUT_HANDLE",
        "    sub rsp, 32",
        "    call GetStdHandle",
        "    add rsp, 32",
        "    cmp rax, -1",
        "    je .create_file",
        "    test rax, rax",
        "    je .create_file",
        f"    mov [rsp + {global_context.var_map['console_handle']}], rax",
        "    jmp .handle_ok",
        ".create_file:",
        "    lea rcx, [rel debug_log]",
        "    mov rdx, 0x40000000 ; GENERIC_WRITE",
        "    xor r8, r8",
        "    xor r9, r9",
        "    sub rsp, 56",
        "    mov qword [rsp + 32], 2 ; CREATE_ALWAYS",
        "    mov qword [rsp + 40], 0x80 ; FILE_ATTRIBUTE_NORMAL",
        "    mov qword [rsp + 48], 0",
        "    call CreateFileA",
        "    add rsp, 56",
        "    cmp rax, -1",
        "    je error_handler",
        f"    mov [rsp + {global_context.var_map['console_handle']}], rax",
        "    mov byte [rel is_file], 1",
        ".handle_ok:",
        "; Register exception handler",
        "    mov rcx, 1 ; First",
        "    lea rdx, [rel ExceptionHandler]",
        "    sub rsp, 32",
        "    call AddVectoredExceptionHandler",
        "    add rsp, 32",
        "; Debug: Console handle",
        "    lea rdx, [rel debug_handle]",
        "    mov r8, 16 ; length of 'Console handle: '",
        "    call append_string",
        f"    mov rax, [rsp + {global_context.var_map['console_handle']}]",
        "    call print_number",
        "    lea rdx, [rel newline]",
        "    mov r8, 2",
        "    call append_string",
        "; Debug: Stack space",
        "    lea rdx, [rel debug_stack]",
        "    mov r8, 13 ; length of 'Stack space: '",
        "    call append_string",
        f"    mov rax, {stack_space}",
        "    call print_number",
        "    lea rdx, [rel newline]",
        "    mov r8, 2",
        "    call append_string",
        "; Debug: Variable offsets",
        "    lea rdx, [rel debug_offsets]",
        "    mov r8, 19 ; length of 'Variable offsets:\\r\\n'",
        "    call append_string"
    ]
    for var, label in var_debug_labels.items():
        text_section += [
            f"    lea rdx, [rel {label}]",
            f"    mov r8, {len(var) + 2} ; length of '{var}: '",
            "    call append_string",
            f"    mov rax, {global_context.var_map[var]}",
            "    call print_number",
            "    lea rdx, [rel newline]",
            "    mov r8, 2",
            "    call append_string"
        ]
    text_section += [
        "    call flush_buffer ; Flush debug info early"
    ]
    text_section += init_after_prologue

    # Generate main program code
    for stmt in ast:
        if verbose_generator:
            stmt_type = type(stmt).__name__
            line = getattr(stmt, 'line', 'unknown')
            print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Processing top-level {stmt_type} at {input_file}[{line}]\033[0m")
        if isinstance(stmt, FunctionCall):
            func_def = next((f for f in ast if isinstance(f, FunctionDefinition) and f.name == stmt.name), None)
            if func_def and should_inline(func_def):
                text_section.append(f"; Inline function {stmt.name} at {input_file}[{stmt.line}]")
                new_context = FunctionContext(global_context.stack_offset)
                for i, (arg, param) in enumerate(zip(stmt.args, func_def.params)):
                    offset = new_context.add_variable(param, 'number' if isinstance(arg, Number) else 'string')
                    text_section += gen_arg_to_register_or_stack(arg, i, global_context, func_def)
                    text_section.append(f"    mov [rsp + {offset}], {['rcx', 'rdx', 'r8', 'r9'][i if i < 4 else 0]} ; Store param {param}")
                text_section += gen_block(func_def.body, f"inline_{stmt.name}", stmt.line, func_def=func_def, inlined=True, inlining_stack={func_def.name}, context=new_context)
            else:
                text_section += gen_function_call(stmt, global_context, use_registers=True)
        elif isinstance(stmt, Assignment):
            text_section += gen_expr(stmt.expr, "rax", dest_var=stmt.var, context=global_context)
        elif isinstance(stmt, Print):
            text_section += gen_error(stmt) if stmt.is_error else gen_print(stmt, global_context, global_context)
        elif isinstance(stmt, IfStatement):
            text_section += gen_block([stmt], f"if_{label_count}", stmt.line, context=global_context)
            label_count += 1  # Ensure unique labels
        elif isinstance(stmt, LoopStatement):
            text_section += gen_block([stmt], f"loop_{label_count}", stmt.line, context=global_context)
            label_count += 1  # Ensure unique labels
        elif isinstance(stmt, Declaration):
            # Declarations handled in collect_strings_and_vars, no codegen needed here
            continue

    text_section += [
        "; Program exit",
        "    call flush_buffer",
        "    cmp byte [rel is_file], 1",
        "    jne .no_close",
        f"    mov rcx, [rsp + {global_context.var_map['console_handle']}]",
        "    sub rsp, 32",
        "    call CloseHandle",
        "    add rsp, 32",
        ".no_close:",
        "; Pause console: Wait for keypress before exiting",
        "    mov rcx, -10 ; STD_INPUT_HANDLE",
        "    sub rsp, 32",
        "    call GetStdHandle",
        "    add rsp, 32",
        "    mov rcx, rax ; Input handle",
        "    lea rdx, [rel bytes_written] ; Reuse bytes_written as dummy buffer for 1 byte",
        "    mov r8, 1 ; Read 1 byte",
        "    lea r9, [rel bytes_written] ; Bytes read (reuse)",
        "    sub rsp, 40",
        "    mov qword [rsp + 32], 0 ; Overlapped = NULL",
        "    call ReadFile",
        "    add rsp, 40",
        *emit_exit(0),
        "error_handler:",
        "; Handle invalid console handle",
        "    call flush_buffer",
        *emit_exit(1)
    ]

    # Generate non-inlined functions
    for stmt in ast:
        if isinstance(stmt, FunctionDefinition) and not should_inline(stmt):
            if verbose_generator:
                print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Generating non-inlined function {stmt.name} at {input_file}[{stmt.line}]\033[0m")
            func_context = FunctionContext(32)  # New context for function
            count_variables(stmt.body, func_context)
            func_stack_space = ((func_context.stack_offset + 15) // 16) * 16
            text_section.append(f"; Function {stmt.name} at {input_file}[{stmt.line}]")
            text_section.append(f"{stmt.name}:")
            text_section.append(f"    sub rsp, {func_stack_space} ; Allocate function stack")
            text_section.append("    and rsp, -16 ; Align stack")
            for i, param in enumerate(stmt.params[:4]):  # First four params in registers
                reg = ['rcx', 'rdx', 'r8', 'r9'][i]
                offset = func_context.add_variable(param, 'number')  # Assume number for simplicity
                text_section.append(f"    mov [rsp + {offset}], {reg} ; Store param {param}")
            for i, param in enumerate(stmt.params[4:]):  # Additional params on stack
                offset = func_context.add_variable(param, 'number')
                text_section.append(f"    mov rax, [rsp + {func_stack_space + 8 * i + 8}] ; Load param {param}")
                text_section.append(f"    mov [rsp + {offset}], rax ; Store param")
            text_section += gen_block(stmt.body, f"func_{stmt.name}", stmt.line, func_def=stmt, inlined=False, context=func_context)
            text_section.append(f"    add rsp, {func_stack_space} ; Restore stack")
            text_section.append("    ret ; Return from function")

    text_section += get_libdivide_helper_asm().splitlines()

    # Write to output file with platform-appropriate line endings
    if verbose_generator:
        print(f"\033[93mildzc[generator:{inspect.currentframe().f_lineno}] Writing assembly to {output_file}, lines: {len(data_section) + len(text_section)}\033[0m")

    with open(output_file, "w", encoding='utf-8', newline='') as f:
        f.write(os.linesep.join(data_section + [""] + text_section))

    # Optionally, print to console for debugging
    #if verbose_generator:
    #    print(f"\nildzc[{inspect.currentframe().f_lineno}] Generated assembly:")
    #    print(os.linesep.join(data_section + [""] + text_section))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"ildzc[{inspect.currentframe().f_lineno}] [ERROR] missing input.\nildzc needs an input file to compile, but only got {sys.argv}.\n{HELP_MESSAGE}")
        sys.exit(1)
    
    input_file = sys.argv[1]
    if input_file == "-help":
        print(f"ildzc[{inspect.currentframe().f_lineno}] {HELP_MESSAGE}")
        sys.exit(1)

    for arg in sys.argv[2:]:
        if arg not in VALID_FLAGS:
            print(f"ildzc[{inspect.currentframe().f_lineno}] [ERROR] unknown flag: {arg}\n{HELP_MESSAGE}")
            sys.exit(1)
        if arg in {"-android", "-ios", "-linux", "-macos"}:
            print(f"ildzc[{inspect.currentframe().f_lineno}] [ERROR] platform '{arg}' is not yet supported.")
            sys.exit(1)
        if arg in ("-nl"):
            nl = True
        if arg in ("-release"):
            release = True
        if arg in ("-verbose", "-verbose-generator"):
            verbose_generator = True
        if arg in ("-verbose", "-verbose-parser"):
            verbose_parser = True
        if arg in ("-verbose", "-verbose-optimizer"):
            verbose_optimizer = True
        if arg in ("-verbose", "-verbose-lexer"):
            verbose_lexer = True

    base_name = os.path.splitext(input_file)[0]
    output_asm = base_name + ".asm"
    output_obj = base_name + ".obj"
    output_exe = base_name + ".exe"

    try:
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"ildzc[{inspect.currentframe().f_lineno}] Input file '{input_file}' not found")

        with open(input_file, "r") as f:
            code = f.read()

        if not code.strip():
            raise ValueError(f"ildzc[{inspect.currentframe().f_lineno}] Input file is empty")

    except FileNotFoundError as e:
        print(f"ildzc[{inspect.currentframe().f_lineno}] Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"ildzc[{inspect.currentframe().f_lineno}] Value Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ildzc[{inspect.currentframe().f_lineno}] Failed to read input file: {str(e)}")
        sys.exit(1)

    lexer = Lexer(code, verbose=verbose_lexer)
    tokens = lexer.lex()
    parser = Parser(tokens, verbose=verbose_parser)
    ast = parser.parse()
    optimized_ast = optimize(ast, verbose=verbose_optimizer)
    generate_assembly(optimized_ast, output_asm, input_file)
    print(f"\033[92m[SUCCESS] ildzc[{inspect.currentframe().f_lineno}] Compilation successful. Output written to {output_asm}\033[0m")

    try:
        subprocess.run([
            "nasm.exe",
            "-g",                # enable debug info
            "-F", "cv8",         # choose CodeView debug format for GoLink/Windows
            "-f", "win64",       # output format for Windows 64-bit
            output_asm,
            "-o", output_obj
        ], check=True)
    except subprocess.CalledProcessError:
        print(f"ildzc[{inspect.currentframe().f_lineno}] NASM failed.")
        sys.exit(1)
    try:
        subprocess.run(["golink", "/console", "/debug", "coff", output_obj, "kernel32.dll", "user32.dll"], check=True)
    except subprocess.CalledProcessError:
        print(f"ildzc[{inspect.currentframe().f_lineno}] GoLink failed.")
        sys.exit(1)

    if not nl:
        try:
            subprocess.run([output_exe])
            #x64dbg_path = os.path.abspath(r"x64dbg\x64dbg.exe")
            #exe_path = os.path.abspath(output_exe)
            #dbg_cwd = os.path.dirname(x64dbg_path)
            #subprocess.run([
            #    x64dbg_path,
            #    exe_path
            #], cwd=dbg_cwd, check=True)
        except Exception as e:
            print(f"ildzc[{inspect.currentframe().f_lineno}] Failed to launch executable: {str(e)}")
            sys.exit(1)