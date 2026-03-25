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
