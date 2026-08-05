# Python Execution Sandbox
version: 1.0.0

> Executes Python code in a sandboxed subprocess with timeout enforcement and blocked dangerous patterns.

## Overview

The Python Executor Sandbox allows Cato agents to run Python code safely by:
- Blocking destructive patterns (os.remove, shutil.rmtree, subprocess.run, subprocess.call, socket.connect)
- Enforcing execution timeouts (default 30s)
- Automatically replacing plt.show() with plt.savefig() to capture matplotlib plots
- Returning structured ExecutionResult with stdout, stderr, returncode

## Tool Actions

- `python.execute` — Execute a Python code snippet

<!-- COLD -->
## Examples

### Basic arithmetic
```python
result = await executor.execute("print(1 + 2 + 3)")
# result.stdout == "6\n"
```

### Matplotlib plot capture
```python
code = "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.show()"
result = await executor.execute(code)
# plt.show() replaced with plt.savefig(...) — artifact saved to sandbox/artifacts/
```

### CLI usage
```bash
cato exec "print('hello world')"
cato exec "import math; print(math.pi)" --timeout 10
```

## Security

The following patterns are blocked and raise `SandboxViolationError`:
- `os.remove`
- `shutil.rmtree`
- `subprocess.run`
- `subprocess.call`
- `socket.connect`

## Artifacts

Saved plots are stored in: `~/.cato/workspace/sandbox/artifacts/`
