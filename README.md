# ildz-compiler
>Ambitious personal project, but I want to keep this going for years to come. I limit it to only target my personal hardware to start. It's a very rough document; the compiler is still partly conceptual. I have various prototypes and parts of it scattered around.

## Overview
Compiler for the **Ildz programming language**, a minimal low-level language that compiles **directly to optimized x86/x86-64 machine code** and produces native **Windows PE executables**. There is no intermediate runtime, virtual machine, or external dependency layer. Standard library is built in.

The compiler targets x86-family architectures only and bypasses assembly generation entirely, emitting optimal machine instructions directly. It does so by massively narrowing the scope (e.g. only targeting very specific scenarios, types of programs, CPUs, high-end RTX cards, instruction sets, etc. (I still have a lot of research to do on this, and I'll save that until I actually have a workable demo). As such it's very much a personal project; I aim to benchmark and optimize the code specifically for my setup before I expand. This design provides precise control over code generation and enables aggressive optimization focused on real-world performance and small binary size.

Ildz intentionally keeps its syntax small and constrained. The goal is to make systems-level programming more accessible than traditional low-level languages, while still maintaining a close and transparent mapping to the underlying hardware. I am merciless here; I want no wasted symbols or punctuation, and I also want the characters to look pretty on the page. I do not at all care about readability; once the syntax is final, it's only a matter of acclimating to it.

Programs are designed to be easy to read and write, without obscuring performance. The compiler, by contrast, provides detailed statistics and explanations of what it does. Logging is enabled by default, and flags can be used to disable it. The compiler prioritizes optimal performance over literal instructions—it doesn’t just execute what you specify, it executes what is most efficient.

This makes the system somewhat experimental: there may be side effects, and it’s intended for exploration and learning. Later, you can tweak your approach and reconsider your design choices. The compiler clearly explains each optimization stage, what changes were made, and how your code could be written differently to avoid certain operations altogether.

Errors are not overwhelming. Compilation stops at the first issue, and if the compiler can resolve it automatically, it does so while explaining what it changed and why.

## Philosophy
Ildz is designed around the idea that systems programming should not require a complex ecosystem. The language and compiler deliberately avoid the traditional C-style toolchain model.

The design emphasizes automation, minimalism, and performance. Ildz is lightweight, delegating as much responsibility as possible to the compiler so tasks are executed faster, the programmer does less manual work, and intervention is straightforward when needed.

A central feature is the compiler’s “intelligence”: it tracks memory, analyzes code, optimizes programs, and enforces optimal layouts and practices. The language and rules are strict, but the compiler guides the programmer explicitly and concisely. Where possible, it automatically fixes issues, notifying the programmer only of the optimization applied or the error resolved.

## Compiler Architecture

The compiler performs the full pipeline internally:
* Lexing and parsing.
* Symbol resolution.
* Optimization.
* Machine code generation.

There are no header files, include chains, manual linking steps, DLL configurations, makefiles, build scripts, or external build systems. There is no fragile import semantics or platform-specific boilerplate.

The compiler handles symbol resolution, dependency ordering, and code integration automatically. It relies on aggressive caching, hashing, and background monitoring, supported by built-in symbol tables and libraries.

Initially, only Windows, Vulkan, and GLFW are targeted. These libraries are parsed and transpiled into .ildz once, then stored in /thirdparty, allowing the compiler to treat their symbols like any native library. Developing this transpiler is a substantial project in itself, with the long-term goal of supporting additional headers and libraries through the same mechanism.

The language enforces strict no-aliasing: the compiler eliminates conflicting symbols entirely. This enables extremely fast build and resolution times, allowing the full pipeline to execute efficiently, even for repeated or incremental builds.

There will not be a package manager nor any external libraries.

## Language Characteristics

* Small, constrained syntax—prioritizing characters that are easy to type, don’t require held keys and appear compact and clean.
* Explicit control over memory and execution—you don’t manually create arenas or memory blocks. The compiler handles allocation and deallocation optimally; you simply specify your intent, and it determines the most efficient way to manage memory throughout the program’s lifetime.
* No hidden runtime behavior—everything that happens is visible and predictable, with no surprises from implicit operations.
* Close and transparent mapping to hardware
* Designed for simple, self-contained programs
Ildz does not attempt to be general-purpose or abstract-heavy. It is intentionally narrow in scope and optimized for clarity, predictability, and performance.

## Design Goals
* Clarity and simplicity for the programmer by offloading as much as possible to the compiler.
* Faster execution and compile times than C in targeted scenarios.
* A simpler mental model than traditional systems languages.

## Intended Audience
This project is primarily of interest to developers exploring:
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
>NOTE: There is nothing to see here; not ready yet.
start with tuts/basics.ildz
check out the other files there for deeper dives
then demos/