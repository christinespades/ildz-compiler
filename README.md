# ildz-compiler
>This is an ambitious long-term personal project that I expect to continue developing for many years. To keep the scope manageable, the compiler currently targets only my own hardware. The documentation is still quite rough, and the compiler itself is in a very early stage of development.

>Once the project is mature enough, the primary way to contribute will be by submitting bug reports. Contributors will be encouraged to write small programs, test the generated output, and identify any issues. Bug reports should include a clear description of the problem along with the source code needed to reproduce it.

>Contributions in other forms are also welcome. Suggestions for language features and improvements are appreciated, and experienced developers who are interested in becoming more directly involved are welcome to reach out about contributing to the implementation itself.

## Overview
Compiler for the **Ildz programming language**, a minimal low-level language that aims to compile **directly to (optimized) x86/x86-64 machine code** and produce native **Windows PE executables** as well as offering JIT execution. There is no intermediate runtime, virtual machine, or external dependency layer. Standard library is built in.

The compiler targets x86-family architectures only (for now) and bypasses assembly generation entirely, emitting machine instructions directly. It does so by massively narrowing the scope (it only supports the very minimum needed for now, and I will expand the language, compiler as I find the need when rewriting C code to ildz. I aim to benchmark and optimize the code specifically for my setup before I (potentially) expand to other software and hardware.

Ildz intentionally keeps its syntax small and constrained. The goal is to make systems-level programming more accessible than traditional low-level languages, while still maintaining a close and transparent mapping to the underlying hardware. I am merciless here; I want no wasted symbols or punctuation, and I also want the characters to look pretty on the page, to be fast to type, and to flow like English. I do not at all care about convention, and I will sacrifice readibility, since once the syntax is final, no matter how obscure, it's really only a matter of acclimating to it.

Given that one understands the syntax, the code will be very explicit and easy to read and write. Additionally, the compiler provides detailed diagnostics and explanations of what it does. Long gone is the endless cascades of warnings, errors or annoying limitations that very rarely actually communicate the issue, let alone how to fix it. In ildz, compiler autopilot is built in along with surgical error messages. Naturally, command line flags can be used to adjust its behavior. In the default setting, to what extent possible, the compiler prioritizes optimal performance over literal instructions—it doesn’t just execute what you specify, it executes what is most efficient. The compiler clearly explains each optimization stage, what changes were made, and how your code could be written differently to avoid certain operations altogether.

Once again: errors are not overwhelming. Compilation stops at the first issue, and if the compiler can resolve it automatically, it does so while explaining what it changed and why, unless you don't want it to.

## Philosophy
Ildz is designed around the idea that systems programming should not require a complex ecosystem. The language and compiler deliberately avoid the traditional C-style toolchain model and contains every thing it needs internally, natively.

The design emphasizes automation, minimalism, and performance. Ildz is lightweight, delegating as much responsibility as possible to the compiler so tasks are executed faster, the programmer does less manual work, and intervention is straightforward when needed.

A central feature is the compiler’s “intelligence”: it tracks memory, analyzes code, optimizes programs, and enforces optimal layouts and practices. More technical details on this later... The language and rules are strict, but the compiler guides the programmer explicitly and concisely.

## Compiler Architecture

The compiler performs the full pipeline internally: multithreaded and multi-pass parsing/lexing/tokenizing/symbol resolution and AST construction, along with deep optimizations in various IRs before lowering, codegen, and then straight to execution. All of this  at high speeds, afforded by comprehensive graphs and analyses made on large caches of mapped and hashed binary data.

// ast, ir gen, constnat folding, copy propagation, coalescing, dead move removal, linear scan allocation, x86 emission


/*no apparanetly: IR generation
      |
constant folding
      |
build live intervals
      |
build interference information
      |
conservative coalescing
      |
linear scan allocation with eviction
      |
x86 emission*/


Parser
    ↓
AST
    ↓
SSA Builder
    ↓
Constant Folding
    ↓
Sparse Constant Propagation
    ↓
Dead Code Elimination
    ↓
Copy Propagation
    ↓
Common Subexpression Elimination
    ↓
Loop Invariant Code Motion
    ↓
Strength Reduction
    ↓
Linear Scan Register Allocation
    ↓
Phi Elimination
    ↓
x86-64 JIT

## Language Characteristics
There are no header files, include chains, manual linking steps, DLL configurations, makefiles, build scripts, or external build systems. There is no fragile import semantics or platform-specific boilerplate. There are just .ildz files. You specify your root program file, and every .ildz in its directory and below is available to you, along with ildzlib, the standard library.

Initially, as far as APIs are concerned, only Windows, Vulkan, and GLFW are targeted. Again: there won't be header files, DLLs or anything of the kind, symbols are nativized in .ildz. 

The language enforces strict no-aliasing: the compiler eliminates conflicting symbols entirely. This enables extremely fast build and resolution times, allowing the full pipeline to execute efficiently, even for repeated or incremental builds.

* Small, constrained syntax—prioritizing characters that are easy to type, don’t require held keys and appear compact and clean, and words/names that read like English, or close to it, at least.
* Explicit control over memory and execution—you don’t manually create arenas or memory blocks, unless you want to (though then it might get optimized away, unless you disable that). The compiler handles allocation and deallocation optimally; you simply specify your intent in code, and it determines the most efficient way to manage memory throughout the program’s lifetime.
* No hidden runtime behavior—everything that happens is visible and predictable, with no surprises from implicit operations.
* Close and transparent mapping to hardware.
* Designed for simple, self-contained programs.
Ildz does not attempt to be general-purpose or abstract-heavy. It is intentionally narrow in scope and optimized for clarity, predictability, and performance.

## Design Goals
Both via the compiler and the language itself:
* Clarity, brevity and precision in communication and affordances.
* Speed and simplicity for the programmer by offloading as much work as possible to the compiler.
* Faster execution and compile times than C in targeted scenarios (maybe, I'm not that focused on benchmarks or optimization yet).
* A simpler mental model than traditional systems languages.

## Intended Audience
This project is primarily of interest to developers exploring:
* An approach to the compiler as both mentor and "dictator".
* Perhaps excessively detailed analyses and structures.
* Ruthless optimization/minimalism.
* Compiler and language design.
* Direct machine code generation.
* Ultra-fast compilation pipelines.
* Minimalist systems programming on Windows.
* Experimental/creative/aesthetic approaches.

## License & Usage
Copyright © 2025-2026 Christine Spades. All rights reserved.

This repository is proprietary software.
Unauthorized copying, modification, redistribution, hosting, or commercial use is strictly prohibited.

No license is granted except by explicit written permission from the author.

# Usage/how-to/learning
>NOTE: There is nothing to see here yet