#pragma once
#include "ic_types.def"
#define ARRAY_COUNT(arr) (sizeof(arr) / sizeof((arr)[0]))
#include "ic_windows.def"
#include "ic_ansi.def"
#define LOG_LINE_INNER(log_func, text, ...) \
    log_func(text, ##__VA_ARGS__, " line ", g_cur_line_no, " in ", g_current_file, ":\n", g_cur_line_no, " |", ansi_italic(g_line))
#define loginfline(text, ...) LOG_LINE_INNER(loginf, text, ##__VA_ARGS__)
#define loginflinev(text, ...) LOG_LINE_INNER(loginfv, text, ##__VA_ARGS__)
#define loginflinergb(text, ...) LOG_LINE_INNER(loginfrgb, text, ##__VA_ARGS__)
#define logerrline(text, ...) LOG_LINE_INNER(logerr, text, ##__VA_ARGS__)
#include "ic_memory.def"
#include "ic_math_float.def"
#include "ic_int.def"
#include "ic_string_view.def"
#include "ic_string.def"
#include "ic_wchar.def"
#include "ic_enum.def"
#include "ic_log_write.def"
#include "ic_log_color.def"
#include "ic_log_args.def"
#include "ic_log_macros.def"
#include "ic_variable_kind.def"
#include "ic_local_symbol.def"
#include "ic_build_mode.def"
#include "ic_config.def"
#include "ic_process.def"
#include "ic_assignment_op.def"
#include "ic_ast_node.def"
#include "ic_hash.def"
typedef struct {
    ASTNode* node;
    const char* scope_name;
    StringView target_sv;
    StringView type_sv;
    bool is_known;
    bool is_function_decl; // True if this record represents the 'fn' definition itself
    u32 ref_count;         // Total occurrences where target_name is invoked/referenced
    const char* first_occurrence_file_name;
    u32 first_occurrence_line_no;
    const char* first_occurrence_line_text;
} Symbol;
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
#include "ic_parser_ctx.def"
#include "ic_arena.def"
#include "ic_path.def"
#include "ic_file.def"
#include "ic_symbol.def"
#include "ic_float.def"
#include "ic_scan.def"
#include "ic_parse_numeric.def"
#include "ic_parse_assignment.def"
#include "ic_parse_type.def"
#include "ic_parse_identifier.def"
#include "ic_parse_space_indent_line.def."
#include "ic_parse_fn_decl.def"
#include "ic_parse_fn_if.def"
#include "ic_parse_fn_as.def"
#include "ic_parse_expression.def"
#include "ic_parse_var_global.def"
#include "ic_parse_fn_ret.def"
#include "ic_parse_var_local.def"
#include "ic_parse_fn_body.def"
#include "ic_ir_opcode.def"
#include "ic_phi_input.def"
#include "ic_ir_kind.def"
#include "ic_ir_operand.def"
#include "ic_ir_type.def"
#include "ic_ir_instruction.def"
#include "ic_ir_phi_incomplete.def"
#include "ic_ir_basic_block.def"
#include "ic_ir_program.def"
#include "ic_ir_ssa_state.def"
#include "ic_ir_lower_context.def"
#include "ic_ir.def"
#include "ic_ast_to_ir.def"
#include "ic_ir_phi.def"
#include "ic_ir_ssa.def"
#include "ic_ir_lower.def"
#include "ic_ir_jit_label.def"
#include "ic_ir_jit_patch.def"
#include "ic_ir_jit_buffer.def"
#include "ic_ir_label.def"
#include "ic_ir_init.def"
#include "ic_ir_emit.def"
#include "ic_ir_emit_x86.def"
#include "ic_ir_emit_x64.def"
#include "ic_ir_emit_function.def"
#include "ic_ir_emit_ir_op.def"
#include "ic_ir_emitter.def"
#include "ic_ir_constant_fold.def"
#include "ic_ir_dead_code_elimination.def"
#include "ic_parse_comment.def"
#include "ic_parse_struct.def"
#include "ic_parse.def"
#include "ic_ir_register_allocation.def"
#include "ic_ir_bytecode.def"
#include "ic_ir_bytecode_exe.def"
#include "ic_main.def"