# ildz-compiler
> **Status:** Development is currently paused. This repository is preserved for future continuation.

## Overview
Compiler for the **Ildz programming language**, a minimal low-level language that compiles **directly to x86/x86-64 machine code** and produces native **Windows PE executables**. There is no intermediate runtime, virtual machine, or external dependency layer.

The compiler targets x86-family architectures only and bypasses assembly generation entirely, emitting machine instructions directly. This design provides precise control over code generation and enables aggressive optimization focused on real-world performance and small binary size.

Ildz intentionally keeps its syntax small and constrained. The goal is to make systems-level programming more accessible than traditional low-level languages, while still maintaining a close and transparent mapping to the underlying hardware. Programs are designed to be simple to read and write without hiding performance characteristics.

## Philosophy
Ildz is designed around the idea that systems programming should not require a complex ecosystem. The language and compiler deliberately avoid the traditional C-style toolchain model.

There are:
* No header files or include chains
* No manual linking steps or DLL configuration
* No makefiles, build scripts, or external build systems
* No fragile import semantics or platform-specific boilerplate

The compiler handles symbol resolution, dependency ordering, and code integration automatically.

The design is inspired by Jai’s philosophy, but pushed further toward minimalism. Ildz aims to be even more lightweight, with more responsibility shifted into the compiler so that the language itself stays small, explicit, and easy to reason about.

## Compiler Architecture

The compiler performs the full pipeline internally:
* Lexing and parsing
* Symbol resolution
* Optimization
* Machine code generation

Symbol resolution is automatic and heavily optimized, using aggressive and detailed caching systems. This allows the entire pipeline to run extremely fast, even for repeated or incremental builds. The intent is to make compilation feel near-instant while still operating at a low, explicit level.

The compiler targets x86-family architectures only and is currently focused on Windows PE output.

## Language Characteristics

* Small, constrained syntax
* Explicit control over memory and execution
* No hidden runtime behavior
* Close and transparent mapping to hardware
* Designed for simple, self-contained programs
Ildz does not attempt to be general-purpose or abstract-heavy. It is intentionally narrow in scope and optimized for clarity, predictability, and performance.

## Design Goals
* Direct generation of native Windows executables
* Zero-runtime, zero-dependency binaries
* Minimal syntax with low conceptual overhead
* Predictable performance and small output size
* Faster execution than C in targeted scenarios
* Faster compile times through aggressive caching
* A simpler mental model than traditional systems languages

## Intended Audience
This project is primarily of interest to developers exploring:
* Compiler and language design
* Direct machine code generation
* Ultra-fast compilation pipelines
* Minimalist systems programming on Windows

## License & Usage
Copyright © 2025-2026 Christineee. All rights reserved.

This repository is proprietary software.
Unauthorized copying, modification, redistribution, hosting, or commercial use is strictly prohibited.

No license is granted except by explicit written permission from the author.
