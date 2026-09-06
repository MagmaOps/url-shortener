---
inclusion: always
---

# Shell Environment

The integrated terminal on this machine is **Git Bash** (MINGW64 on Windows), always. All shell commands run in Git Bash, not `cmd.exe` or PowerShell.

## Rules

- Use Bash syntax and POSIX-style forward-slash paths (e.g. `.venv/Scripts/python.exe`), not backslash paths.
- Do NOT wrap commands in `cmd /c "..."`. On this machine that spawns an interactive `cmd` shell that only prints the Windows banner and hangs at a prompt without running the command.
- The Python virtual environment interpreter is at `.venv/Scripts/python.exe` (Windows venv layout). Invoke it directly, e.g. `.venv/Scripts/python.exe -m pytest`.
- Redirects like `2>&1` work normally in Git Bash. Avoid `> nul` (a Windows-ism) — in Git Bash it creates a real file named `nul` in the working directory, which breaks tools like pytest collection. Use `/dev/null` instead.
- Prefer standard Unix tools (`ls`, `rm`, `grep`, `cat`) available in Git Bash over their Windows equivalents.
