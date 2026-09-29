"""Execution grader: functional correctness by running the generated code.

Grades a code-completion prompt the way the HumanEval reference harness does
(openai/human-eval, MIT license, https://github.com/openai/human-eval): the
program

    prompt + completion + "\\n" + test + "\\n" + check(entry_point)

is executed in a fresh Python process with a wall-clock timeout, and the
problem is passed if and only if it runs to completion without raising.
There is no partial credit: a problem is worth 100 or 0, so a suite's
unweighted pass rate is exactly the standard pass@1.

The completion is used exactly as the model produced it. The reference
harness does not strip markdown fences or otherwise repair the text, and
neither does this grader -- a fenced completion is a SyntaxError here,
exactly as it would be under the reference harness.

Security
--------
The child process runs untrusted model-generated code. It is isolated in a
throwaway working directory with stdin closed, runs under Python's isolated
mode (-I), and applies a reliability guard (adapted from the reference
harness, MIT) that removes the most destructive builtins before the program
runs. This is a guard, not a sandbox: the reference harness says the same,
and model-generated code can still misbehave. Run suites that use this
grader on a machine you can afford to have poked at.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_OUTPUT_TAIL_CHARS = 2000

# The child writes this sentinel (via os.write, which the guard does not
# neutralise) after the check program returns normally. An exit code of 0
# alone is not proof the tests ran: model code that calls sys.exit(0) would
# otherwise "pass" without check() ever executing. Under the reference
# harness the same code raises SystemExit, which is caught and scored as a
# failure -- the sentinel keeps the two harnesses agreeing.
_SENTINEL = b"__LOCALBENCH_EXEC_OK__\n"

# Reliability guard, adapted from human_eval/execution.py (openai/human-eval,
# MIT license). Runs inside the child process, before the check program.
# No memory limit is applied, matching the reference harness's default run.
_GUARD_PREAMBLE = '''
def _localbench_reliability_guard():
    import faulthandler
    faulthandler.disable()

    import builtins
    builtins.exit = None
    builtins.quit = None

    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    os.kill = None
    os.system = None
    os.putenv = None
    os.remove = None
    os.removedirs = None
    os.rmdir = None
    os.fchdir = None
    os.setuid = None
    os.fork = None
    os.forkpty = None
    os.killpg = None
    os.rename = None
    os.renames = None
    os.truncate = None
    os.replace = None
    os.unlink = None
    os.fchmod = None
    os.fchown = None
    os.chmod = None
    os.chown = None
    os.chroot = None
    os.lchflags = None
    os.lchmod = None
    os.lchown = None
    os.getcwd = None
    os.chdir = None

    import shutil
    shutil.rmtree = None
    shutil.move = None
    shutil.chown = None

    import subprocess
    subprocess.Popen = None

    import sys
    sys.modules["ipdb"] = None
    sys.modules["joblib"] = None
    sys.modules["resource"] = None
    sys.modules["psutil"] = None
    sys.modules["tkinter"] = None


_localbench_reliability_guard()

'''

_SENTINEL_EPILOGUE = (
    "import os as _localbench_os\n"
    "_localbench_os.write(1, " + repr(_SENTINEL) + ")\n"
)


def build_check_program(prompt: str, completion: str, test_code: str, entry_point: str) -> str:
    """Assemble the check program, byte-identical to the reference harness."""
    return prompt + completion + "\n" + test_code + "\n" + f"check({entry_point})"


def _result(status: str, passed: bool, output_tail: str = "") -> dict[str, Any]:
    return {
        "passed": passed,
        "score": 100.0 if passed else 0.0,
        "max_score": 100.0,
        "details": {"status": status, "output_tail": output_tail},
    }


def _tail(path: str, limit: int = MAX_OUTPUT_TAIL_CHARS) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except OSError:
        return ""
    if len(data) <= limit:
        return data
    return "..." + data[-limit:]


def run_execution(config: dict, completion: str, prompt_text: str = "") -> dict[str, Any]:
    """Grade one code-completion response by executing its test suite.

    config keys:
      test_code       source of the problem's unit tests (defines check)
      entry_point     name of the function under test
      timeout_seconds wall-clock limit for the whole run (default 3.0)
      language        must be "python" (the only supported language)
      completion_mode "body" (default/reference contract) or "full_function"

    prompt_text is the code prefix the model completed (the prompt's user
    message). The result dict matches the deterministic graders' contract:
    {"passed", "score", "max_score", "details"}, with details.status one of
    "passed", "timed out", or "failed: ..." -- the reference harness's three
    classifications.
    """
    try:
        if config.get("language", "python") != "python":
            return _result(f"failed: unsupported language {config.get('language')!r}", False)
        test_code = config.get("test_code", "")
        entry_point = config.get("entry_point", "")
        timeout = float(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        completion_mode = config.get("completion_mode", "body")
        if completion_mode not in {"body", "full_function"}:
            return _result("failed: unsupported completion mode", False)
        if not (test_code and entry_point and (prompt_text or completion_mode == "full_function")):
            return _result("failed: incomplete execution grader config", False)

        prefix = prompt_text if completion_mode == "body" else ""
        program = build_check_program(prefix, completion or "", test_code, entry_point)
        try:
            compile(program, "<candidate>", "exec")
        except SyntaxError as exc:
            result = _result(f"failed: invalid Python ({type(exc).__name__}: {exc.msg})", False)
            result["details"]["failure_category"] = "invalid_code"
            return result
        child_src = _GUARD_PREAMBLE + program + "\n" + _SENTINEL_EPILOGUE

        with tempfile.TemporaryDirectory(prefix="localbench-exec-") as td:
            prog_path = os.path.join(td, "check_program.py")
            out_path = os.path.join(td, "output.txt")
            with open(prog_path, "w", encoding="utf-8") as f:
                f.write(child_src)
            env = dict(os.environ, OMP_NUM_THREADS="1")
            try:
                with open(out_path, "wb") as out:
                    proc = subprocess.run(
                        [sys.executable, "-I", prog_path],
                        cwd=td,
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        env=env,
                        timeout=timeout,
                    )
            except subprocess.TimeoutExpired:
                result = _result("timed out", False, _tail(out_path))
                result["details"]["failure_category"] = "execution_timeout"
                return result
            if proc.returncode != 0:
                return _result(f"failed: exit {proc.returncode}", False, _tail(out_path))
            try:
                with open(out_path, "rb") as f:
                    completed = _SENTINEL in f.read()
            except OSError:
                completed = False
            if not completed:
                return _result(
                    "failed: process exited 0 without completing the tests "
                    "(early exit in generated code)",
                    False,
                    _tail(out_path),
                )
            return _result("passed", True)
    except Exception as e:
        return _result(f"failed: {e}", False)
