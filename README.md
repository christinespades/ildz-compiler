# ildz-compiler

> **Status:** Development is currently paused. This repository is preserved for future continuation.

Compiler for the **Ildz programming language**, a minimal low-level language that compiles **directly to x86/x86-64 machine code** and produces native **Windows PE executables**. There is no intermediate runtime, virtual machine, or external dependency layer.

The compiler targets x86-family architectures only and bypasses assembly generation entirely, emitting machine instructions directly. This design provides precise control over code generation and enables aggressive optimization focused on real-world performance and small binary size.

Ildz intentionally keeps its syntax small and constrained. The goal is to make systems-level programming more accessible than traditional low-level languages, while still maintaining a close and transparent mapping to the underlying hardware. Programs are designed to be simple to read and write without hiding performance characteristics.

### Design goals

* Direct generation of native Windows executables
* Minimal syntax for small, self-contained software
* Predictable performance with low overhead
* Faster execution than C in targeted scenarios
* Lower conceptual overhead than Python while retaining control

This project is primarily of interest to developers exploring compiler construction, direct machine code generation, and bare-metal-style efficiency on Windows systems.
