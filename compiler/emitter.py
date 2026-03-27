import struct

class Emitter:
    def __init__(self):
        self.text = bytearray()
        self.rdata = bytearray()
        self.data = bytearray()
        self.labels = {}
        self.relocations = []
        self.strings = {}

        self.text_rva = 0x1000
        self.rdata_rva = 0x2000
        self.data_rva = 0x3000
        self.entry_point_rva = self.text_rva

        self.regs = {"a": 10, "b": 11}  # prototype register allocation

        # addresses of API stubs (to be patched)
        self.std_handle_offset = None
        self.write_console_offset = None

    # -------------------------
    # Strings
    # -------------------------
    def add_string(self, s):
        if s in self.strings:
            return self.strings[s]
        offset = len(self.rdata)
        self.rdata.extend(s.encode("utf-8") + b"\0")
        self.strings[s] = offset
        return offset

    # -------------------------
    # Labels
    # -------------------------
    def define_label(self, name):
        self.labels[name] = len(self.text)

    def patch_label(self, name, patch_offset, relative=True):
        self.relocations.append((name, patch_offset, relative))

    def finalize_labels(self):
        for name, patch_offset, relative in self.relocations:
            if name not in self.labels:
                raise Exception(f"Undefined label {name}")
            target = self.labels[name]
            if relative:
                rel = target - (patch_offset + 4)
                self.text[patch_offset:patch_offset+4] = struct.pack("<i", rel)
            else:
                self.text[patch_offset:patch_offset+8] = struct.pack("<Q", target)

    # -------------------------
    # x86-64 instruction helpers
    # -------------------------
    def mov_imm64_reg(self, imm, reg):
        rex = 0x49
        opcode = 0xB8 + (reg & 7)
        self.text.append(rex)
        self.text.append(opcode)
        self.text.extend(struct.pack("<Q", imm))

    def mov_reg_reg(self, src, dst):
        # add reg -> reg mov prototype (hardcoded r10->r11)
        self.text.extend([0x4C, 0x89, 0xD3])

    def lea_reg_rip(self, reg, offset):
        # lea reg, [rip + offset]
        rex = 0x4C | ((reg >> 3) << 2)
        self.text.append(0x4C)
        self.text.append(0x8D)
        modrm = 0x05 | ((reg & 7) << 3)
        self.text.append(modrm)
        self.text.extend(struct.pack("<i", offset))

    def call_rel32(self, label):
        self.text.append(0xE8)
        patch_offset = len(self.text)
        self.text.extend(b'\x00\x00\x00\x00')
        self.patch_label(label, patch_offset)

    def ret(self):
        self.text.append(0xC3)

    # -------------------------
    # Print via WriteConsoleA
    # -------------------------
    def emit_Print(self, node):
        if isinstance(node.value, str):
            offset = self.add_string(node.value)

            # RCX = handle (stdout) via GetStdHandle(-11)
            # We'll use a helper label STDOUT_HANDLE that stores handle in .data
            # Load RCX from that memory
            self.text.extend([0x48, 0x8B, 0x0D])  # mov rcx, [rip+offset]
            rel = self.data_rva - (self.text_rva + len(self.text) + 4)
            self.text.extend(struct.pack("<i", rel))

            # RDX = address of string
            self.text.extend([0x48, 0x8D, 0x15])
            rel_str = self.rdata_rva + offset - (self.text_rva + len(self.text) + 4)
            self.text.extend(struct.pack("<i", rel_str))

            # R8 = length of string
            length = len(node.value)
            self.mov_imm64_reg(length, 12)  # r12 = length

            # R9 = null
            self.mov_imm64_reg(0, 13)  # r13 = NULL

            # call WriteConsoleA
            self.call_rel32("WRITE_CONSOLE")

    # -------------------------
    # AST emission
    # -------------------------
    def emit_Program(self, node):
        for stmt in node.statements:
            self.emit(stmt)
        self.ret()

    def emit_Assignment(self, node):
        if isinstance(node.value, int):
            self.mov_imm64_reg(node.value, self.regs.get(node.name, 10))

    # -------------------------
    # PE writing (minimal)
    # -------------------------
    def write_pe(self, filename):
        dos_stub = b"MZ" + b"\x00"*58 + struct.pack("<I", 0x80)
        pe_sig = b"PE\0\0"
        coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 0xF0, 0)
        optional = struct.pack("<HBBIIIIQQQQHHHHHH",
                               0x20B,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)
        with open(filename, "wb") as f:
            f.write(dos_stub)
            f.write(pe_sig)
            f.write(coff)
            f.write(optional)
            # sections
            f.write(self.text)
            f.write(self.rdata)
            f.write(self.data)