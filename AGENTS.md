# Engineering constraints

- Target Canon EOS R5 Mark I, installed firmware 2.0.0 as reported by the owner on 2026-10-21. The corresponding firmware file and ROM identity have not been independently verified.
- Prefer the smallest evidence-backed change. Refactor our own code when it simplifies the work; do not build a generic patch framework in advance.
- Link version-pinned sources for hardware/firmware assumptions. Do not treat another model's address, a filename, a header guess, or a matching hash as compatibility evidence.
- Current scope is offline inspection and QEMU-EOS research. Synthetic emulator-only test programs are allowed; they must contain no Canon bytes and must never be packaged as camera install files. No camera installer, USB/PTP command, physical boot flag/NVRAM write, or camera register patch belongs in this delivery.
- Before proposing device execution, establish the exact firmware and an independently reviewed boot/recovery path. RAM execution alone does not establish safety. Do not assume removing the card reverses persistent changes.
- Before each delivery, run relevant tests and document possible bricking mechanisms, what was actually tested, and remaining unknowns. Host tests cannot certify camera safety.
- Keep firmware images, dumps, serial numbers, credentials, and generated camera data out of this public repository. Inspect staged contents explicitly; ignore rules are not a complete safeguard.
- No subagents, extra services, dependencies, or scaffolding unless needed for concrete work.
