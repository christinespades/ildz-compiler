#pragma once

#include "ic_types.def"

#define ARRAY_COUNT(arr) (sizeof(arr) / sizeof((arr)[0]))
#define MAX_PATH 260

#include "ic_windows.def"

unsigned int g_cur_line_no = 0;
bool g_compiler_log_verbose = false;
char g_line[1024];
char g_project_root_path[MAX_PATH];
const char* g_current_file;
#define ansi_italic(str) "\x1b[3m", str, "\x1b[23m"
#define LOG_LINE_INNER(log_func, text, ...) \
    log_func(text, ##__VA_ARGS__, " line ", g_cur_line_no, " in ", g_current_file, ":\n", g_cur_line_no, " |", ansi_italic(g_line))
#define loginfline(text, ...) LOG_LINE_INNER(loginf, text, ##__VA_ARGS__)
#define loginflinev(text, ...) LOG_LINE_INNER(loginfv, text, ##__VA_ARGS__)
#define loginflinergb(text, ...) LOG_LINE_INNER(loginfrgb, text, ##__VA_ARGS__)
#define logerrline(text, ...) LOG_LINE_INNER(logerr, text, ##__VA_ARGS__)
// Also need to add
// div     floating division
// idiv    integer division
// mod     remainder
typedef enum {
    VAR_LOCAL_PARAM,
    VAR_LOCAL_VAR,
    VAR_GLOBAL
} VariableKind;
typedef struct
{
    const char* data;
    u32 length;
} StringView;
StringView true_sv  = { .data = "true",  .length = 4 };
StringView false_sv = { .data = "false", .length = 5 };
typedef struct {
    const char* name;
    u32 length;
    VariableKind kind;
    StringView type_sv;
} LocalSymbol;
#define MAX_LOCAL_SYMBOLS 16
#define MAX_SCOPE_DEPTH 64

#include "ic_ast_node.def"

typedef struct {
    ASTNode* node;
    const char* scope_name;
    StringView target_sv;
    StringView type_sv;
    bool is_known;
    bool is_function_decl; // True if this record represents the 'fn' definition itself
    u32 ref_count;         // Total occurrences where target_name is invoked/referenced
} Symbol;

#define MAX_COMPILATION_UNITS 1024
static ASTNode* g_ast_roots[MAX_COMPILATION_UNITS];
static u32 g_ast_root_count = 0;

#define MAX_FILE 4096
#define MAX_GLOBAL_SYMBOLS 16384
static Symbol g_symbol_registry[MAX_GLOBAL_SYMBOLS];
static u32 g_symbol_count = 0;

#define MAX_UNKNOWN_SYMBOLS 16384
static Symbol g_unknown_symbol_registry[MAX_UNKNOWN_SYMBOLS];
static u32 g_unknown_symbol_count = 0;

typedef struct {
    ASTNode* node;
    u32 indent_level;
} ScopeFrame;

typedef struct {
    u32 cursor;
    bool in_function_scope;
    bool in_struct_scope;
    bool expecting_empty_line;
    u32 total_paths;
    u32 returning_paths;
    ASTNode* last_stmt;
    LocalSymbol local_symbols[MAX_LOCAL_SYMBOLS];
    u32 local_symbol_count;
    u32 current_indent;
    u32 if_nesting_level;
    u32 while_nesting_level;
    ScopeFrame scope_stack[MAX_SCOPE_DEPTH];
    u32 scope_depth;
    ASTNode* current_fn_node;   // Direct pointer to current function's AST node
    StringView current_fn_type; // Active function's return type ("v", "bl", etc.)
} ParserCtx;

#include "ic_memory.def"
#include "ic_math_float.def"
#include "ic_enum.def"
#include "ic_int.def"
#include "ic_string.def"
#include "ic_log.def"
#include "ic_ansi.def"
#include "ic_path.def"
#include "ic_file.def"
#include "ic_symbol.def"
#include "ic_float.def"
bool is_valid_id_char(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}
bool is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }
bool is_digit(char c) { return c >= '0' && c <= '9'; }
#include "ic_scan.def"
void write_indent(void* out, int indent)
{
    for (int i = 0; i < indent; i++) file_write_character(' ', out);
}
#include "ic_arena.def"
#include "ic_parse_numeric.def"
#include "ic_parse_assignment.def"
#include "ic_parse_type.def"
#include "ic_parse_identifier.def"
#include "ic_parse_var_global.def"
#include "ic_parse_space_indent_line.def."
#include "ic_parse_fn_decl.def"
#include "ic_parse_fn_if.def"
#include "ic_parse_fn_as.def"
#include "ic_parse_expression.def"
#include "ic_parse_fn_ret.def"
#include "ic_parse_var_local.def"
#include "ic_parse_fn_body.def"
#include "ic_ast_to_ir.def"
#include "ic_parse_comment.def"
#include "ic_parse_struct.def"
#include "ic_parse.def"
#include "ic_ir_to_bytecode.def"
#include "ic_main.def"