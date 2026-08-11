"""Child-process entrypoint: loads one tool module by path and calls its
run() with JSON arguments, printing the result to stdout.

    python -m yozhan_runtime.sandbox.runner <tool.py path> <json args>

Kept dependency-free and tiny on purpose — this is what executes inside the
sandbox, so the less it does, the smaller the trusted surface.
"""

from __future__ import annotations

import importlib.util
import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: runner <tool_path> <json_args>", file=sys.stderr)
        return 2

    tool_path, raw_args = argv[1], argv[2]
    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        print(f"invalid tool arguments: {exc}", file=sys.stderr)
        return 2

    spec = importlib.util.spec_from_file_location("yozhan_sandboxed_tool", tool_path)
    if spec is None or spec.loader is None:
        print(f"cannot load tool at {tool_path}", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run = getattr(module, "run", None)
    if run is None:
        print(f"tool at {tool_path} has no run()", file=sys.stderr)
        return 2

    try:
        sys.stdout.write(str(run(**arguments)))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
