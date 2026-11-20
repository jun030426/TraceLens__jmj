# Learning-only C tracer (docs/06: C는 GDB). Loaded inside gdb with `-x`; it single-steps the
# student's main.c and writes one JSON object per stop to $LERNY_TRACE_OUT.
# Reads memory only through gdb — it never calls functions in the inferior.
import json
import os
import re

import gdb

SOURCE = os.environ.get("LERNY_SOURCE_NAME", "main.c")
MAX_STEPS = int(os.environ.get("LERNY_MAX_STEPS", "5000"))
STDOUT_PATH = os.environ["LERNY_STDOUT"]
OUT = open(os.environ["LERNY_TRACE_OUT"], "w", encoding="utf-8")
MAX_ITEMS = 20
MAX_DEPTH = 3

try:
    with open(SOURCE, encoding="utf-8") as _src:
        SOURCE_LINES = _src.read().splitlines()
except OSError:
    SOURCE_LINES = []
FOR_HEADER = re.compile(r"^\s*(?:\}\s*)?for\s*\(")


def is_for_header(line):
    return 0 < line <= len(SOURCE_LINES) and bool(FOR_HEADER.match(SOURCE_LINES[line - 1]))


state = {"signal": None, "exited": False, "stdout_sent": 0}
object_ids = {}


def on_stop(event):
    if isinstance(event, gdb.SignalEvent):
        state["signal"] = event.stop_signal


def on_exit(_event):
    state["exited"] = True


gdb.events.stop.connect(on_stop)
gdb.events.exited.connect(on_exit)


def read_stdout():
    try:
        with open(STDOUT_PATH, "rb") as f:
            f.seek(state["stdout_sent"])
            data = f.read(65536)
    except OSError:
        return ""
    state["stdout_sent"] += len(data)
    return data.decode("utf-8", "replace")


def prim(text, type_name):
    if len(text) > 80:
        text = text[:80] + "…"
    return {"k": "prim", "v": text, "t": type_name}


def obj_id(key):
    if key not in object_ids:
        object_ids[key] = len(object_ids) + 1
    return object_ids[key]


def address(value):
    try:
        return int(value.address) if value.address is not None else None
    except gdb.error:
        return None


def c_string(value, limit=80):
    try:
        return '"' + value.string(length=limit) + '"'
    except (gdb.error, gdb.MemoryError, UnicodeDecodeError):
        return None


def char_text(code):
    return "'" + chr(code) + "'" if 32 <= code < 127 else str(code)


def serialize(value, objects, depth=0):
    t = value.type.strip_typedefs()
    code = t.code
    try:
        if code == gdb.TYPE_CODE_BOOL:
            return prim("true" if int(value) else "false", "bool")
        if code == gdb.TYPE_CODE_INT:
            if t.sizeof == 1 and str(t).endswith("char"):
                return prim(char_text(int(value) & 0xFF), "char")
            return prim(str(int(value)), "int")
        if code == gdb.TYPE_CODE_CHAR:
            return prim(char_text(int(value) & 0xFF), "char")
        if code == gdb.TYPE_CODE_FLT:
            return prim(repr(float(value)), "float")
        if code == gdb.TYPE_CODE_ENUM:
            return prim(str(value), "int")
        if code == gdb.TYPE_CODE_PTR:
            return pointer(value, t, objects, depth)
        if code == gdb.TYPE_CODE_ARRAY:
            return array(value, t, objects, depth)
        if code == gdb.TYPE_CODE_STRUCT:
            return struct(value, t, objects, depth)
    except (gdb.error, gdb.MemoryError):
        return prim("읽을 수 없음", "unknown")
    return prim(str(t), "unsupported")


def pointer(value, t, objects, depth):
    target = t.target().strip_typedefs()
    raw = int(value)
    if raw == 0:
        return prim("NULL", "null")
    if target.code in (gdb.TYPE_CODE_INT, gdb.TYPE_CODE_CHAR) and target.sizeof == 1:
        text = c_string(value)
        return prim(text, "str") if text is not None else prim("포인터", "pointer")
    if target.code == gdb.TYPE_CODE_STRUCT:
        # 단일 포인터·연결 리스트 (docs/06): only follow pointers to structs, and only when
        # the memory is readable right now. Anything else stays an opaque pointer.
        try:
            return struct(value.dereference(), target, objects, depth)
        except (gdb.error, gdb.MemoryError):
            return prim("unknown", "pointer")
    return prim("포인터", "pointer")


def array(value, t, objects, depth):
    lo, hi = t.range()
    n = hi - lo + 1
    elem = t.target().strip_typedefs()
    if elem.sizeof == 1 and elem.code in (gdb.TYPE_CODE_INT, gdb.TYPE_CODE_CHAR):
        text = c_string(value[lo].address, limit=n)
        if text is None:
            return prim("", "str")
        return prim(text[1:-1].split("\x00")[0].join('""'), "str")
    oid = obj_id(("array", address(value), str(t)))
    ref = {"k": "ref", "id": oid}
    if oid in objects:
        return ref
    if depth > MAX_DEPTH:
        objects[oid] = {"id": oid, "type": "list", "truncated": True}
        return ref
    objects[oid] = {"id": oid, "type": "list"}
    shown = min(n, MAX_ITEMS)
    objects[oid] = {
        "id": oid,
        "type": "list",
        "items": [serialize(value[lo + i], objects, depth + 1) for i in range(shown)],
        "n": n,
        "truncated": n > MAX_ITEMS,
    }
    return ref


def struct(value, t, objects, depth):
    name = t.tag or t.name or "struct"
    oid = obj_id(("struct", address(value), name))
    ref = {"k": "ref", "id": oid}
    if oid in objects:
        return ref
    if depth > MAX_DEPTH:
        objects[oid] = {"id": oid, "type": name, "truncated": True}
        return ref
    objects[oid] = {"id": oid, "type": name}  # reserve against cycles (linked lists)
    entries = []
    for field in t.fields()[:MAX_ITEMS]:
        if field.name is None or field.bitpos is None:
            continue
        entries.append([field.name, serialize(value[field.name], objects, depth + 1)])
    objects[oid] = {"id": oid, "type": name, "entries": entries}
    return ref


def user_frames():
    frames = []
    f = gdb.newest_frame()
    while f is not None:
        sal = f.find_sal()
        if sal.symtab is not None and sal.symtab.filename.endswith(SOURCE):
            frames.append(f)
        f = f.older()
    frames.reverse()  # outermost first
    return frames


stack = []  # [{"fid", "func", "visited": set(lines)}]
next_fid = [0]
steps = [0]


def emit(kind, record, line, locals_=None, objects=None, error=None):
    steps[0] += 1
    parent = stack[-2]["fid"] if len(stack) >= 2 and stack[-1] is record else None
    if record in stack:
        i = stack.index(record)
        parent = stack[i - 1]["fid"] if i > 0 else None
    event = {
        "kind": kind,
        "fid": record["fid"],
        "parent": parent,
        "func": record["func"],
        "line": line,
        "locals": locals_,
        "objects": objects or {},
        "stdout": read_stdout(),
    }
    if error:
        event["error"] = error
    OUT.write(json.dumps(event, ensure_ascii=False) + "\n")


def visible_locals(frame, record, line):
    objects = {}
    out = {}
    try:
        block = frame.block()
    except RuntimeError:
        return {}, {}
    seen = set()
    while block is not None:
        for sym in block:
            if not (sym.is_variable or sym.is_argument) or sym.name in seen:
                continue
            seen.add(sym.name)
            # A local whose declaration has not run yet holds garbage (or last pass's value) —
            # not a fact. Only a for-header declaration stays valid when the header comes round.
            if not sym.is_argument and not (
                sym.line < line
                or (sym.line == line and is_for_header(line) and line in record["visited"])
            ):
                continue
            try:
                out[sym.name] = serialize(sym.value(frame), objects)
            except (gdb.error, gdb.MemoryError):
                out[sym.name] = prim("읽을 수 없음", "unknown")
        if block.function is not None:
            break
        block = block.superblock
    return out, objects


def snapshot(kind):
    frames = user_frames()
    if not frames:
        return False
    # close frames that are gone (returned or unwound) — no return value is invented
    while len(stack) > len(frames):
        gone = stack[-1]
        emit("return", gone, gone.get("cur", 0))
        stack.pop()
    while len(stack) < len(frames):
        f = frames[len(stack)]
        record = {"fid": next_fid[0], "func": f.name() or "?", "visited": set()}
        next_fid[0] += 1
        stack.append(record)
        line = f.find_sal().line
        locals_, objects = visible_locals(f, record, line)
        emit("call", record, line, locals_, objects)
        record["cur"] = line
    top = frames[-1]
    if stack[-1]["func"] != (top.name() or "?"):
        # same depth, different function: the previous call returned and a new one started
        emit("return", stack[-1], stack[-1].get("cur", 0))
        stack.pop()
        record = {"fid": next_fid[0], "func": top.name() or "?", "visited": set()}
        next_fid[0] += 1
        stack.append(record)
        emit("call", record, top.find_sal().line, *visible_locals(top, record, top.find_sal().line))
        record["cur"] = top.find_sal().line
    record = stack[-1]
    line = top.find_sal().line
    if record.get("cur") == line and record.get("fresh", True):
        # the call event already showed this stop; a second identical stop teaches nothing
        record["fresh"] = False
        return True
    record["fresh"] = False
    if record.get("cur") is not None and record["cur"] != line:
        # a line counts as executed once the frame has moved past it (declarations included)
        record["visited"].add(record["cur"])
    locals_, objects = visible_locals(top, record, line)
    emit(kind, record, line, locals_, objects)
    record["cur"] = line
    return True


def finish_out():
    try:
        gdb.execute("finish", to_string=True)
    except gdb.error:
        pass


def main():
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    gdb.execute("set width 0")
    gdb.execute("set startup-with-shell off")
    gdb.execute("start", to_string=True)
    clipped = False
    error = None
    while not state["exited"]:
        if steps[0] >= MAX_STEPS:
            clipped = True
            break
        sig = state["signal"]
        if sig is not None:
            names = {"SIGSEGV": "Segmentation fault", "SIGFPE": "Floating point exception",
                     "SIGABRT": "Aborted"}
            error = f"{sig}: {names.get(sig, '프로그램이 신호로 멈췄습니다')}"
            if stack:
                frames = user_frames()
                if frames:
                    line = frames[-1].find_sal().line
                    locals_, objects = visible_locals(frames[-1], stack[-1], line)
                    emit("exception", stack[-1], line, locals_, objects, error)
            break
        try:
            frame = gdb.selected_frame()
        except gdb.error:
            break
        sal = frame.find_sal()
        if sal.symtab is None or not sal.symtab.filename.endswith(SOURCE):
            finish_out()
            continue
        snapshot("line")
        try:
            gdb.execute("step", to_string=True)
        except gdb.error:
            break
    tail = read_stdout()
    OUT.write(json.dumps({"kind": "end", "clipped": clipped, "stdout": tail, "error": error},
                         ensure_ascii=False) + "\n")
    OUT.close()
    try:
        gdb.execute("kill", to_string=True)
    except gdb.error:
        pass


main()
