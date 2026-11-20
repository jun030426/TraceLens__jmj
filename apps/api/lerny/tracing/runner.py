"""Sandbox entry point: `python -m lerny.tracing.runner --language c|java|python < source`.

Prints one TraceEnvelope JSON to stdout. This module executes student code, so it must only be
started inside the trace sandbox (service.py builds that command); it is never imported by the API.
"""

import argparse
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lerny.tracing.envelope import TraceBuilder

HERE = Path(__file__).resolve().parent
MAX_SOURCE_BYTES = 32 * 1024
COMPILE_TIMEOUT = 20
TRACE_TIMEOUT = 10
DEFAULT_MAX_EVENTS = 5000


def limits(memory_mb: int | None):
    def apply():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
        if memory_mb:
            size = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (size, size))

    return apply


def run(cmd, cwd, timeout, memory_mb=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        preexec_fn=limits(memory_mb),
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", **(env or {})},
        stdin=subprocess.DEVNULL,
    )


def compile_error(text: str, pattern: str) -> dict:
    for line in text.splitlines():
        m = re.match(pattern, line)
        if m:
            info = m.groupdict()
            return {
                "line": int(info["line"]),
                "column": int(info["col"]) if info.get("col") else None,
                "message": info["msg"].strip(),
                "text": None,
            }
    return {"line": None, "column": None, "message": text.strip()[:500], "text": None}


def feed(builder: TraceBuilder, lines) -> tuple[str | None, bool]:
    """Debugger stops → envelope events. Returns (runtime error, clipped)."""
    error, clipped, pending_stdout = None, False, ""
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        stop = json.loads(raw)
        if stop["kind"] == "end":
            error, clipped = stop.get("error"), stop.get("clipped", False)
            pending_stdout += stop.get("stdout", "")
            break
        objects = {int(k): v for k, v in stop.get("objects", {}).items()}
        builder.record(
            stop["kind"], stop["fid"], stop["parent"], stop["func"], stop["line"],
            stop["locals"], objects, stop.get("stdout", ""), stop.get("error"), stop.get("returned"),
        )
    if pending_stdout and builder.events:
        builder.events[-1]["stdout"] += pending_stdout
    return error, clipped or builder.clipped


def trace_java(source: str, work: Path, max_events: int) -> dict:
    builder = TraceBuilder("java", max_events)
    m = re.search(r"public\s+(?:final\s+)?class\s+([A-Za-z_]\w*)", source)
    main_class = m.group(1) if m else "Main"
    src = work / f"{main_class}.java"
    src.write_text(source, encoding="utf-8")
    classes = work / "classes"
    classes.mkdir()
    javac = run(["javac", "-g", "-encoding", "UTF-8", "-d", str(classes), src.name], work,
                COMPILE_TIMEOUT)
    if javac.returncode != 0:
        info = compile_error(javac.stderr.decode("utf-8", "replace"),
                             r"^[^:]+\.java:(?P<line>\d+): error: (?P<msg>.*)$")
        return builder.envelope(source, "compile_error", "컴파일 오류", info)
    tracer_dir = java_tracer_dir()
    try:
        proc = run(
            ["java", "-cp", str(tracer_dir), "LernyJavaTracer", str(classes), main_class,
             str(max_events), "256"],
            work, TRACE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as timeout:
        partial = (timeout.stdout or b"").decode("utf-8", "replace").splitlines()
        feed(builder, partial[:-1])  # the last line may be cut mid-write
        builder.clipped = True
        return builder.envelope(source, "timeout", "실행 시간이 너무 깁니다 (10초 제한)",
                                truncation_reason="timeout")
    error, clipped = feed(builder, proc.stdout.decode("utf-8", "replace").splitlines())
    builder.clipped = clipped
    return builder.envelope(source, "runtime_error" if error else "ok", error)


def java_tracer_dir() -> Path:
    """The sandbox image precompiles the tracer; a dev checkout compiles it once on demand."""
    built = Path(os.environ.get("LERNY_JAVA_TRACER_DIR", HERE / "java" / "build"))
    if (built / "LernyJavaTracer.class").exists():
        return built
    built.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "-d", str(built), str(HERE / "java" / "LernyJavaTracer.java")],
                   check=True, capture_output=True)
    return built


def trace_c(source: str, work: Path, max_events: int) -> dict:
    builder = TraceBuilder("c", max_events)
    (work / "main.c").write_text(source, encoding="utf-8")
    gcc = run(
        ["gcc", "-std=c17", "-g", "-O0", "-fno-omit-frame-pointer",
         "-include", str(HERE / "c" / "lerny_prelude.h"), "main.c", "-o", "main", "-lm"],
        work, COMPILE_TIMEOUT, memory_mb=256,
    )
    if gcc.returncode != 0:
        info = compile_error(gcc.stderr.decode("utf-8", "replace"),
                             r"^main\.c:(?P<line>\d+):(?P<col>\d+): (?:fatal )?error: (?P<msg>.*)$")
        return builder.envelope(source, "compile_error", "컴파일 오류", info)
    trace_out = work / "trace.jsonl"
    try:
        run(
            ["gdb", "-q", "-nx", "-batch", "-x", str(HERE / "c" / "gdb_tracer.py"), "./main"],
            work, TRACE_TIMEOUT,
            env={
                "LERNY_STDOUT": str(work / "stdout.txt"),
                "LERNY_TRACE_OUT": str(trace_out),
                "LERNY_MAX_STEPS": str(max_events),
                "LERNY_SOURCE_NAME": "main.c",
            },
        )
    except subprocess.TimeoutExpired:
        builder.clipped = True
        lines = trace_out.read_text("utf-8").splitlines() if trace_out.exists() else []
        feed(builder, lines)
        return builder.envelope(source, "timeout", "실행 시간이 너무 깁니다 (10초 제한)",
                                truncation_reason="timeout")
    lines = trace_out.read_text("utf-8").splitlines() if trace_out.exists() else []
    error, clipped = feed(builder, lines)
    builder.clipped = clipped
    return builder.envelope(source, "runtime_error" if error else "ok", error)


def trace_python(source: str, work: Path, max_events: int) -> dict:
    """Same sys.settrace tracer the browser uses, run in a separate CPython process."""
    builder = TraceBuilder("python", max_events)
    script = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(HERE)!r})\n"
        "from python_tracer import run_traced\n"
        "run_traced(sys.stdin.read(), lambda s: print(s), int(sys.argv[1]))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", script, str(max_events)],
        input=source.encode(), capture_output=True, timeout=TRACE_TIMEOUT, cwd=work,
        preexec_fn=limits(256), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    done = {}
    for chunk in proc.stdout.decode("utf-8", "replace").splitlines():
        parsed = json.loads(chunk)
        if isinstance(parsed, dict):
            done = parsed
            continue
        for e in parsed:
            builder.events.append({
                "seq": e["seq"], "kind": e["kind"], "frame_id": e["frameId"],
                "parent_frame_id": e["parentFrameId"], "func": e["func"],
                "caused_by_line": e["causedByLine"], "observed_at_line": e["observedAtLine"],
                "locals_delta": e["localsDelta"], "objects_delta": e["objectsDelta"],
                "stdout": e["stdout"],
                **({"error": e["error"]} if "error" in e else {}),
                **({"returned": e["returned"]} if "returned" in e else {}),
            })
    builder.clipped = bool(done.get("clipped"))
    syntax = done.get("syntaxError")
    if syntax:
        info = {"line": syntax["line"], "column": syntax["offset"], "message": syntax["msg"],
                "text": syntax["text"], "name": syntax["name"]}
        return builder.envelope(source, "compile_error", done.get("error"), info)
    error = done.get("error")
    return builder.envelope(source, "runtime_error" if error else "ok", error)


TRACERS = {"java": trace_java, "c": trace_c, "python": trace_python}


def trace(language: str, source: str, max_events: int = DEFAULT_MAX_EVENTS) -> dict:
    if len(source.encode()) > MAX_SOURCE_BYTES:
        raise ValueError("source too large")
    work = Path(tempfile.mkdtemp(prefix="lerny-trace-"))
    try:
        try:
            return TRACERS[language](source, work, max_events)
        except subprocess.TimeoutExpired:
            builder = TraceBuilder(language, max_events)
            return builder.envelope(source, "timeout", "실행 시간이 너무 깁니다 (10초 제한)",
                                    truncation_reason="timeout")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=sorted(TRACERS), required=True)
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    args = parser.parse_args()
    source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1).decode("utf-8")
    json.dump(trace(args.language, source, args.max_events), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
