import os
import platform
import shutil

import pytest
from fastapi import HTTPException

from lerny.tracing.envelope import TraceBuilder
from lerny.tracing import service

INT = {"k": "prim", "t": "int"}


def test_builder_emits_only_changes_like_the_python_tracer():
    b = TraceBuilder("c")
    arr = {1: {"id": 1, "type": "list", "items": [{**INT, "v": "2"}], "n": 1, "truncated": False}}
    b.record("call", 0, None, "main", 3, {}, {})
    b.record("line", 0, None, "main", 4, {"a": {"k": "ref", "id": 1}}, arr)
    b.record("line", 0, None, "main", 5, {"a": {"k": "ref", "id": 1}}, arr)
    first, second, third = b.events
    assert first["caused_by_line"] is None and second["caused_by_line"] == 3
    assert [d["name"] for d in second["locals_delta"]] == ["a"]
    assert len(second["objects_delta"]) == 1
    assert third["locals_delta"] == [] and third["objects_delta"] == []


def test_builder_drops_a_repeated_stop_that_changes_nothing():
    b = TraceBuilder("c")
    b.record("line", 0, None, "main", 4, {"x": {**INT, "v": "1"}}, {})
    b.record("line", 0, None, "main", 4, {"x": {**INT, "v": "1"}}, {})
    assert len(b.events) == 1


def test_unreadable_frame_claims_no_change():
    b = TraceBuilder("java")
    b.record("line", 1, 0, "f", 4, {"x": {**INT, "v": "1"}}, {})
    b.record("return", 1, 0, "f", 4, None, {})
    assert b.events[-1]["locals_delta"] == []


def test_builder_marks_clipping_at_the_event_cap():
    b = TraceBuilder("java", max_events=2)
    for line in range(5):
        b.record("line", 0, None, "main", line, {"i": {**INT, "v": str(line)}}, {})
    env = b.envelope("x")
    assert len(env["events"]) == 2 and env["clipped"] and env["truncation_reason"] == "max_events"


def test_no_sandbox_means_no_execution(monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: type("S", (), {"trace_sandbox_command": []})())
    with pytest.raises(HTTPException) as err:
        service.run_in_sandbox("c", "int main(void){return 0;}")
    assert err.value.status_code == 503


# The runner executes code, so these only run inside the trace sandbox image
# (LERNY_TRACE_SANDBOX_TESTS=1), never as part of a normal host test run.
sandbox = pytest.mark.skipif(
    os.environ.get("LERNY_TRACE_SANDBOX_TESTS") != "1" or platform.system() != "Linux",
    reason="trace runner tests run only inside the Linux trace sandbox",
)

BUBBLE_JAVA = """public class Main {
    public static void main(String[] args) {
        int[] arr = {3, 1};
        if (arr[0] > arr[1]) {
            int t = arr[0];
            arr[0] = arr[1];
            arr[1] = t;
        }
        System.out.println(arr[0]);
        int[] b = arr;
        System.out.println(b[2]);
    }
}
"""

LIST_C = """#include <stdio.h>
#include <stdlib.h>
struct Node { int value; struct Node *next; };
int twice(int n) {
    return n * 2;
}
int main(void) {
    struct Node *head = malloc(sizeof(struct Node));
    head->value = twice(2);
    head->next = NULL;
    printf("%d\\n", head->value);
    int *p = NULL;
    *p = 1;
    return 0;
}
"""


def values(events, name):
    return [d.get("value") for e in events for d in e["locals_delta"] if d["name"] == name]


@sandbox
@pytest.mark.skipif(not shutil.which("javac"), reason="JDK missing")
def test_java_trace_shows_arrays_alias_output_and_exception():
    from lerny.tracing.runner import trace

    env = trace("java", BUBBLE_JAVA)
    events = env["events"]
    assert env["status"] == "runtime_error"
    assert env["error"].startswith("ArrayIndexOutOfBoundsException")
    assert "args" not in {d["name"] for e in events for d in e["locals_delta"]}
    arr_id = values(events, "arr")[0]["id"]
    assert values(events, "b")[0]["id"] == arr_id  # alias = same object id
    final = [o["obj"] for e in events for o in e["objects_delta"] if o["obj"]["id"] == arr_id][-1]
    assert [i["v"] for i in final["items"]] == ["1", "3"]
    assert "".join(e["stdout"] for e in events) == "1\n"
    assert events[-1]["kind"] == "exception"


@sandbox
@pytest.mark.skipif(not shutil.which("gdb"), reason="gdb missing")
def test_c_trace_shows_struct_pointer_call_return_and_signal():
    from lerny.tracing.runner import trace

    env = trace("c", LIST_C)
    events = env["events"]
    assert env["status"] == "runtime_error" and env["error"].startswith("SIGSEGV")
    assert [e["func"] for e in events if e["kind"] == "call"] == ["main", "twice"]
    nodes = [o["obj"] for e in events for o in e["objects_delta"] if o["obj"]["type"] == "Node"]
    assert ["value", {"k": "prim", "v": "4", "t": "int"}] in nodes[-1]["entries"]
    assert values(events, "p")[-1] == {"k": "prim", "v": "NULL", "t": "null"}
    assert "".join(e["stdout"] for e in events) == "4\n"


@sandbox
def test_c_compile_error_reports_the_line():
    from lerny.tracing.runner import trace

    env = trace("c", "int main(void) {\n    int x = 1\n    return x;\n}\n")
    assert env["status"] == "compile_error" and env["compile_error"]["line"] == 3
