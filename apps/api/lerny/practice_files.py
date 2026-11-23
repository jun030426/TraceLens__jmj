"""Read source-file evidence for practice without changing retrieval chunks."""

import ast
import hashlib
import io
import json
import re
import sys
import tokenize
from contextlib import nullcontext
from pathlib import Path

from lerny.storage import source_file


CODE_LANGUAGES = {".py": "python", ".java": "java", ".c": "c"}


class FileProbeBudget:
    # Two declarations × (original + four alternatives), plus the fixed-output check.
    limit = 11

    def __init__(self, receipt=None):
        self.receipt = receipt
        self.outputs = {}

    def run(self, source, evaluate):
        from lerny.gemini_provider import receipt_lock, save_json

        key = hashlib.sha256(source.encode()).hexdigest()
        with receipt_lock(self.receipt.with_suffix(".lock")) if self.receipt else nullcontext():
            if self.receipt and self.receipt.is_file():
                self.outputs = json.loads(self.receipt.read_text(encoding="utf-8"))
            if key in self.outputs:
                return self.outputs[key]
            if len(self.outputs) >= self.limit:
                raise ValueError("PRACTICE_PROBES_INEFFECTIVE")
            # A deferred model request can replay the whole worker transaction.
            # Reserve first so an interrupted sandbox submission is never sent twice.
            self.outputs[key] = None
            if self.receipt:
                save_json(self.receipt, self.outputs)
            output = evaluate(source)
            self.outputs[key] = output if output and len(output) <= 4000 else None
            if self.receipt:
                save_json(self.receipt, self.outputs)
            return self.outputs[key]


def verified_file(version, chunks):
    """Bind every selected chunk to the file, preserving original layout and verified context."""
    if (version.extraction_report or {}).get("held_count", 0):
        raise ValueError("PRACTICE_FILE_GAP")
    # Older imports sometimes stored the entire UTF-8 file in one unwrapped chunk.
    if (
        len(chunks) == 1
        and len(chunks[0].content) <= 6000
        and hashlib.sha256(chunks[0].content.encode()).hexdigest() == version.sha256
    ):
        return chunks[0].content, [{"chunk_id": chunks[0].id, "quote": chunks[0].content}]
    try:
        with source_file(version) as path:
            with path.open("rb") as stream:
                raw = stream.read(4 * 6000 + 4)
                if len(raw) == 4 * 6000 + 4:
                    raise ValueError("PRACTICE_FILE_TOO_LONG")
    except FileNotFoundError:
        raise ValueError("PRACTICE_FILE_EVIDENCE") from None
    if hashlib.sha256(raw).hexdigest() != version.sha256:
        raise ValueError("PRACTICE_FILE_EVIDENCE")
    try:
        encoding = (
            tokenize.detect_encoding(io.BytesIO(raw).readline)[0]
            if version.filename.lower().endswith(".py")
            else "utf-8-sig"
        )
        code = raw.decode(encoding)
    except (SyntaxError, UnicodeError, LookupError):
        raise ValueError("PRACTICE_FILE_EVIDENCE") from None
    if len(code) > 6000:
        raise ValueError("PRACTICE_FILE_TOO_LONG")
    language = CODE_LANGUAGES[Path(version.filename).suffix.lower()]
    spans = []
    context = []
    for chunk in chunks:
        engine = (chunk.locator or {}).get("engine", {})
        loc = engine.get("location", {})
        start, end, quote = loc.get("char_start"), loc.get("char_end"), engine.get("code_text")
        if not (
            type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(code)
            and engine.get("source_sha256") == version.sha256
            and engine.get("eligible_for_chunking") is True
            and engine.get("language") == language
            and code[start:end] == quote
            and quote in chunk.content
        ):
            raise ValueError("PRACTICE_FILE_EVIDENCE")
        spans.append((start, end, chunk.id, quote))
        for group in engine.get("class_context", []):
            for (a, b), part in zip(group["source_spans"], group["text_parts"], strict=True):
                if 0 <= a < b <= len(code) and code[a:b] == part:
                    context.append((a, b))

    def supported_gap(start, end):
        gap = code[start:end]
        for a, b in sorted(set(context), reverse=True):
            if start <= a < b <= end:
                gap = gap[: a - start] + " " * (b - a) + gap[b - start :]
        if not gap.strip():
            return True
        if language == "python":
            # Comments and imports may be extraction context outside the indexed functions.
            # A sibling module cannot be supplied to the single-program sandbox.
            try:
                nodes = ast.parse(gap).body
            except SyntaxError:
                return False
            for node in nodes:
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    modules = [node.module or ""]
                else:
                    return False
                if any(name.split(".")[0] not in sys.stdlib_module_names for name in modules):
                    raise ValueError("PRACTICE_EXTERNAL_MODULE")
            return True
        return False

    at = 0
    citations = []
    for start, end, chunk_id, quote in sorted(spans):
        if start < at or not supported_gap(at, start):
            raise ValueError("PRACTICE_FILE_GAP")
        citations.append({"chunk_id": chunk_id, "quote": quote})
        at = end
    if not citations or not supported_gap(at, len(code)):
        raise ValueError("PRACTICE_FILE_GAP")
    return code, citations


def native_console_input(language, code):
    if language == "java":
        return re.search(r"\bSystem\s*\.\s*(?:in|console)\b|\bScanner\b", code) is not None
    return language == "c" and re.search(r"\b(?:stdin|scanf|getchar|gets|read)\b", code) is not None


def fixed_native_program(language, code):
    if language == "java":
        return re.search(r"\bstatic\s+void\s+main\s*\(", code) is not None
    return language == "c" and re.search(r"\bmain\s*\(", code) is not None


def check_program_size(code):
    text = code.replace("\r\n", "\n").strip()
    if len(text) < 20 or sum(bool(line.strip()) for line in text.splitlines()) < 3:
        raise ValueError("PRACTICE_PROGRAM_TOO_SHORT")


def safe_full_prefix(prefix):
    """Only copy imports, comments and plain literal assignments into a full editor."""
    try:
        for node in ast.parse(prefix).body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if not isinstance(node, ast.Assign) or not all(isinstance(t, ast.Name) for t in node.targets):
                return False
            # literal_eval also accepts set() and complex-number arithmetic.
            if any(isinstance(n, (ast.Call, ast.BinOp)) for n in ast.walk(node.value)):
                return False
            ast.literal_eval(node.value)
    except (SyntaxError, ValueError, TypeError):
        return False
    return True


def python_shape(code, *, stdin_only=False):
    shapes = python_shapes(code, stdin_only=stdin_only)
    return shapes[0] if shapes else None


def python_shapes(code, *, stdin_only=False):
    """Identify the immutable declaration(s) and the types of their replacement literals."""
    from lerny.practice_inputs import literal_type, stdin_type

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        raise ValueError("PRACTICE_FILE_SYNTAX") from None
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "input"
    ]
    if stdin_only and not calls:
        return []
    if any(
        any(n in calls for n in ast.walk(loop))
        for loop in ast.walk(tree)
        if isinstance(loop, (ast.For, ast.While, ast.comprehension))
    ):
        raise ValueError("PRACTICE_LOOP_INPUT")
    declarations = []
    literals = []
    lines = code.splitlines(keepends=True)
    for position, node in enumerate(tree.body):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        name = node.targets[0].id
        last_line = lines[node.end_lineno - 1].rstrip("\r\n")
        if last_line.encode()[node.end_col_offset :].split(b"#", 1)[0].strip() or node.col_offset:
            continue
        if node.lineno == node.end_lineno and (kind := stdin_type(node.value)):
            declarations.append((position, node.lineno, name, kind))
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue
        try:
            kind = literal_type(value)
        except (ValueError, TypeError, SyntaxError):
            kind = None
        if kind and kind != "str":
            literals.append((node, name, kind))
    if calls:
        if (
            len(calls) != len(declarations)
            or len(calls) > 6
            or len({name for _, _, name, _ in declarations}) != len(calls)
            or declarations[-1][0] - declarations[0][0] + 1 != len(calls)
        ):
            raise ValueError("PRACTICE_INPUT_POSITION")
        start, end = declarations[0][1], declarations[-1][1]
        return [(
            "stdin",
            "".join(lines[start - 1 : end]).rstrip("\r\n"),
            [(name, kind) for _, _, name, kind in declarations],
        )]
    if any(not name.isupper() for _, name, _ in literals):
        ordered = sorted(literals, key=lambda candidate: (candidate[1].isupper(), candidate[2] != "list"))
        return [("literal", "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip("\r\n"), [(name, kind)])
                for node, name, kind in ordered]
    if not any(
        not isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
        )
        and any(isinstance(x, ast.Call) for x in ast.walk(n))
        for n in tree.body
    ):
        raise ValueError("PRACTICE_NO_ENTRYPOINT")
    return [("fixed", "", [])]
