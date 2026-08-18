# -*- coding: utf-8 -*-
# Algo-Scope Tracer — Pyodide와 로컬 CPython 겸용. sys.settrace 기반.
# 계약: run_traced(code, emit, max_events) → emit(TraceEvent[] JSON) 반복, 마지막 emit({"done":...})
import sys, json, io, contextlib, types, collections

SAFE_TYPES = (int, float, bool, str, type(None))
MAX_ITEMS = 20
MAX_STR = 80
MAX_DEPTH = 2
CHUNK_SIZE = 200


def _prim(v):
    r = repr(v)
    if len(r) > MAX_STR:
        r = r[:MAX_STR] + '…'
    return {'k': 'prim', 'v': r, 't': type(v).__name__}


def _serialize(v, objects, depth=0):
    """값 → Value. 컬렉션·객체는 objects에 ObjectSnap 등록 후 ref 반환. 부작용 없는 경로만."""
    if isinstance(v, SAFE_TYPES):
        return _prim(v)
    oid = id(v)
    ref = {'k': 'ref', 'id': oid}
    if depth > MAX_DEPTH:
        objects[oid] = {'id': oid, 'type': type(v).__name__, 'truncated': True}
        return ref
    if isinstance(v, (types.FunctionType, types.BuiltinFunctionType, types.ModuleType, type)):
        objects[oid] = {'id': oid, 'type': type(v).__name__, 'unsupported': True}
        return ref
    if isinstance(v, (list, tuple, set, collections.deque)):
        items = list(v)[:MAX_ITEMS]
        objects[oid] = {'id': oid, 'type': type(v).__name__,
                        'items': [_serialize(x, objects, depth + 1) for x in items],
                        'truncated': len(v) > MAX_ITEMS}
    elif isinstance(v, dict):
        entries = list(v.items())[:MAX_ITEMS]
        objects[oid] = {'id': oid, 'type': 'dict',
                        'entries': [[str(k)[:MAX_STR], _serialize(x, objects, depth + 1)] for k, x in entries],
                        'truncated': len(v) > MAX_ITEMS}
    else:
        d = getattr(type(v), '__dict__', None) and v.__dict__ if hasattr(v, '__dict__') else None
        if isinstance(d, dict):
            entries = list(d.items())[:MAX_ITEMS]
            objects[oid] = {'id': oid, 'type': type(v).__name__,
                            'entries': [[str(k), _serialize(x, objects, depth + 1)] for k, x in entries]}
        else:
            objects[oid] = {'id': oid, 'type': type(v).__name__, 'unsupported': True}
    return ref


class _Stop(Exception):
    pass


class _Tracer:
    def __init__(self, emit, max_events):
        self.emit = emit
        self.max_events = max_events
        self.buffer = []
        self.seq = 0
        self.clipped = False
        self.frame_ids = {}
        self.next_fid = 0
        self.prev_locals = {}
        self.prev_objects = {}
        self.last_line = {}
        self.stdout = io.StringIO()
        self.stdout_sent = 0

    def _fid(self, frame):
        key = id(frame)
        if key not in self.frame_ids:
            self.frame_ids[key] = self.next_fid
            self.next_fid += 1
        return self.frame_ids[key]

    def _flush(self, force=False):
        if len(self.buffer) >= CHUNK_SIZE or (force and self.buffer):
            self.emit(json.dumps(self.buffer))
            self.buffer = []

    def _new_stdout(self):
        s = self.stdout.getvalue()
        out = s[self.stdout_sent:]
        self.stdout_sent = len(s)
        return out

    def _record(self, frame, kind, err=None):
        if self.clipped:
            return
        if self.seq >= self.max_events:
            self.clipped = True
            raise _Stop()
        fid = self._fid(frame)
        parent = self.frame_ids.get(id(frame.f_back)) if frame.f_back else None
        objects = {}
        cur = {}
        for name, val in frame.f_locals.items():
            if name.startswith('__'):
                continue
            try:
                cur[name] = json.dumps(_serialize(val, objects))
            except Exception:
                cur[name] = json.dumps({'k': 'prim', 'v': '<직렬화 불가>', 't': type(val).__name__})
        prev = self.prev_locals.get(fid, {})
        delta = []
        for name, vjson in cur.items():
            if prev.get(name) != vjson:
                delta.append({'name': name, 'op': 'set', 'value': json.loads(vjson)})
        for name in prev:
            if name not in cur:
                delta.append({'name': name, 'op': 'delete'})
        self.prev_locals[fid] = cur
        obj_delta = []
        for oid, snap in objects.items():
            sjson = json.dumps(snap, sort_keys=True)
            if self.prev_objects.get(oid) != sjson:
                self.prev_objects[oid] = sjson
                obj_delta.append({'op': 'set', 'obj': snap})
        ev = {'seq': self.seq, 'kind': kind, 'frameId': fid, 'parentFrameId': parent,
              'func': frame.f_code.co_name,
              'causedByLine': self.last_line.get(fid), 'observedAtLine': frame.f_lineno,
              'localsDelta': delta, 'objectsDelta': obj_delta, 'stdout': self._new_stdout()}
        if err:
            ev['error'] = err
        self.last_line[fid] = frame.f_lineno
        self.seq += 1
        self.buffer.append(ev)
        self._flush()

    def __call__(self, frame, event, arg):
        if frame.f_code.co_filename != '<user>':
            return None
        if event == 'line':
            self._record(frame, 'line')
        elif event == 'call':
            self.last_line.pop(self._fid(frame), None)
            self._record(frame, 'call')
        elif event == 'return':
            self._record(frame, 'return')
        elif event == 'exception':
            self._record(frame, 'exception', err=f"{arg[0].__name__}: {arg[1]}")
        return self


def run_traced(code, emit, max_events=5000):
    tracer = _Tracer(emit, max_events)
    error = None
    compiled = compile(code, '<user>', 'exec')
    # __name__을 '__main__'으로 주입 — 빈 globals면 builtins의 __name__('builtins')이 잡혀서
    # AI 생성 스크립트에 흔한 `if __name__ == "__main__":` 블록이 통째로 건너뛰어진다
    user_globals = {'__name__': '__main__'}
    with contextlib.redirect_stdout(tracer.stdout):
        sys.settrace(tracer)
        try:
            exec(compiled, user_globals)
        except _Stop:
            pass
        except BaseException as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            sys.settrace(None)
    tracer._flush(force=True)
    emit(json.dumps({'done': True, 'clipped': tracer.clipped, 'error': error}))
