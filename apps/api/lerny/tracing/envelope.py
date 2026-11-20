"""Turns per-stop debugger snapshots into the TraceEvent contract the visualizer consumes.

Java (JDI) and C (GDB) tracers report the full visible state at each stop. This module diffs
consecutive stops into locals_delta / objects_delta exactly like the Python sys.settrace tracer,
so all three languages share one event shape and one renderer.
"""

import hashlib
import json

SCHEMA_VERSION = 1
MAX_EVENTS = 20_000
MAX_ITEMS = 20


class TraceBuilder:
    def __init__(self, language: str, max_events: int = MAX_EVENTS):
        self.language = language
        self.max_events = max_events
        self.events: list[dict] = []
        self.clipped = False
        self.prev_locals: dict[int, dict[str, str]] = {}
        self.prev_objects: dict[int, str] = {}
        self.last_line: dict[int, int] = {}
        self.ids: dict[object, int] = {}

    def object_id(self, raw_key: object) -> int:
        """Debugger identities (JDI unique ids, C addresses) become small run-local ids.

        Raw C addresses must not leak into the learning view (docs/06 trace contract)."""
        if raw_key not in self.ids:
            self.ids[raw_key] = len(self.ids) + 1
        return self.ids[raw_key]

    def full(self) -> bool:
        return len(self.events) >= self.max_events

    def record(
        self,
        kind: str,
        frame_id: int,
        parent_frame_id: int | None,
        func: str,
        line: int,
        locals_: dict[str, dict] | None,
        objects: dict[int, dict],
        stdout: str = "",
        error: str | None = None,
        returned: dict | None = None,
    ) -> bool:
        if self.full():
            self.clipped = True
            return False
        if kind == "call":
            self.last_line.pop(frame_id, None)
        prev = self.prev_locals.get(frame_id, {})
        if locals_ is None:  # the tracer could not read the frame: nothing is claimed to change
            cur = prev
        else:
            cur = {name: json.dumps(value, sort_keys=True) for name, value in locals_.items()}
        locals_delta = [
            {"name": name, "op": "set", "value": json.loads(value)}
            for name, value in cur.items()
            if prev.get(name) != value
        ]
        locals_delta += [{"name": name, "op": "delete"} for name in prev if name not in cur]
        self.prev_locals[frame_id] = cur
        objects_delta = []
        for oid, snap in objects.items():
            encoded = json.dumps(snap, sort_keys=True)
            if self.prev_objects.get(oid) != encoded:
                self.prev_objects[oid] = encoded
                objects_delta.append({"op": "set", "obj": snap})
        last = self.events[-1] if self.events else None
        if (
            kind == "line" and last and last["frame_id"] == frame_id
            and last["observed_at_line"] == line and not locals_delta and not objects_delta
            and not stdout
        ):
            # a debugger can stop twice on one line (stepping over a library call); the second
            # stop changes nothing on screen
            return True
        event = {
            "seq": len(self.events),
            "kind": kind,
            "frame_id": frame_id,
            "parent_frame_id": parent_frame_id,
            "func": func,
            "caused_by_line": self.last_line.get(frame_id),
            "observed_at_line": line,
            "locals_delta": locals_delta,
            "objects_delta": objects_delta,
            "stdout": stdout,
        }
        if error:
            event["error"] = error
        if returned is not None:
            event["returned"] = returned
        self.last_line[frame_id] = line
        self.events.append(event)
        return True

    def envelope(
        self,
        source: str,
        status: str = "ok",
        error: str | None = None,
        compile_error: dict | None = None,
        truncation_reason: str | None = None,
    ) -> dict:
        if self.clipped and not truncation_reason:
            truncation_reason = "max_events"
        return {
            "schema_version": SCHEMA_VERSION,
            "language": self.language,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "status": status,
            "events": self.events,
            "clipped": self.clipped,
            "truncation_reason": truncation_reason,
            "error": error,
            "compile_error": compile_error,
        }


def prim(text: str, type_name: str) -> dict:
    if len(text) > 80:
        text = text[:80] + "…"
    return {"k": "prim", "v": text, "t": type_name}


def ref(object_id: int) -> dict:
    return {"k": "ref", "id": object_id}
