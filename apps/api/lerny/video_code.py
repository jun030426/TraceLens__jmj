"""Offline, source-bound Python code blocks; never invent or execute source text.

Two spatially bound OCR readings must agree, including indentation and literals.
This establishes extraction evidence, not semantic or execution correctness.
Practice creation still requires the existing isolated sandbox checks.
"""
import ast
import io
import math
import re
import statistics
import subprocess
import tokenize
from pathlib import Path

from lerny import local_ocr
from video_extraction.shared.common import digest_file, read, save, signature

POLICY = "video-python-code-v1"
MAX_CODE = 6000
MAX_BLOCKS = 6
BUILTINS = {"print", "input", "int", "float", "str", "list", "tuple", "dict", "set",
            "len", "range", "sum", "min", "max", "abs", "round", "sorted", "enumerate",
            "zip", "map", "bool", "reversed", "any", "all"}
START = re.compile(r"^(?:#|(?:def|class|if|elif|else|for|while|try|except|finally|with|return|"
                   r"import|from|break|continue|pass|assert|raise)\b|[\w.]+\s*(?:\(|(?:[+\-*/%]?=)(?!=))|"
                   r"[\w.]+\[[^\n]+\]\s*=|[)\]}])")


def syntax_checked(code):
    if not isinstance(code, str) or not 20 <= len(code) <= MAX_CODE:
        return False
    if "\x00" in code or "\t" in code or "\ufffd" in code or "..." in code:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return False
    nodes = list(ast.walk(tree))
    # Numeric teaching examples only; do not turn unknown OCR fragments into code.
    if any(isinstance(n, (ast.Import, ast.ImportFrom, ast.AsyncFunctionDef,
                          ast.Await, ast.Yield, ast.YieldFrom)) for n in nodes):
        return False
    stores = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    stores |= {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    stores |= {n.arg for n in nodes if isinstance(n, ast.arg)}
    loads = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    if not loads <= stores | BUILTINS:
        return False
    # A fragment such as print(total), or a prose identifier, is insufficient.
    return (bool(stores) and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                and n.func.id == "print" for n in nodes)
            and not any(isinstance(n, ast.Expr) and not isinstance(n.value, ast.Call)
                        for n in tree.body))


def reading(lines, confidence=None):
    """Recover leading spaces from a monospaced grid; preserve all OCR characters."""
    if not 2 <= len(lines) <= 100:
        raise ValueError("VIDEO_CODE_INCOMPLETE")
    ordered = sorted(lines, key=lambda row: (row["bbox"][1], row["bbox"][0]))
    # A code-only token like print(total) is one OCR word. Require a strict
    # word floor and a character-weighted block score, not prose word frequency.
    if confidence is None:
        total = sum(max(1,len(row["text"])) for row in ordered)
        acceptable = (all(row["min_confidence"] >= 80 for row in ordered)
                      and sum(row["mean_confidence"]*max(1,len(row["text"])) for row in ordered)/total >= 90)
    else:
        acceptable = all(row["min_confidence"] >= confidence[0] and row["mean_confidence"] >= confidence[1] for row in ordered)
    if not acceptable:
        raise ValueError("VIDEO_CODE_LOW_CONFIDENCE")
    for row in ordered:
        box = row["bbox"]
        if (len(box) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
                or not 0 < box[0] < box[2] < 1000 or not 0 < box[1] < box[3] < 1000):
            raise ValueError("VIDEO_CODE_CLIPPED")
    widths = [(w["bbox"][2]-w["bbox"][0])/len(w["text"])
              for row in ordered for w in row.get("words", [])
              if len(w.get("text", "")) >= 4 and w["text"].isascii()]
    if not widths:
        raise ValueError("VIDEO_CODE_INDENT_UNCERTAIN")
    cell = statistics.median(widths)
    if cell <= 0:
        raise ValueError("VIDEO_CODE_INDENT_UNCERTAIN")
    left = min(row["bbox"][0] for row in ordered)
    result = []
    previous = None
    for row in ordered:
        if previous and row["bbox"][1] < previous["bbox"][3] - 2:
            raise ValueError("VIDEO_CODE_OVERLAPPING_LINES")
        offset = (row["bbox"][0]-left)/cell
        spaces = round(offset)
        if spaces > 32 or abs(offset-spaces) > .4:
            raise ValueError("VIDEO_CODE_INDENT_UNCERTAIN")
        result.append(" "*spaces + row["text"])
        previous = row
    code = "\n".join(result)
    if not syntax_checked(code):
        raise ValueError("VIDEO_CODE_INCOMPLETE")
    return code


def code_tokens(code):
    # Ignore only spacing between tokens, never string contents, operators, comments,
    # line boundaries or recovered indentation. The first observation stays unchanged.
    return [(token.type, token.string) for token in tokenize.generate_tokens(io.StringIO(code).readline)
            if token.type != tokenize.ENDMARKER]


def groups(lines):
    group = []
    for index, row in sorted(enumerate(lines), key=lambda item: (item[1]["bbox"][1], item[1]["bbox"][0])):
        text = row["text"].strip()
        prior = lines[group[-1]] if group else None
        if prior and (row["bbox"][1] - prior["bbox"][3] >
                      max(8, 2*(prior["bbox"][3]-prior["bbox"][1]))):
            if len(group) >= 2:
                yield group
            group = []
        if not START.match(text):
            if len(group) >= 2:
                yield group
            group = []
            continue
        group.append(index)
    if len(group) >= 2:
        yield group


def verify_frame(image, folder, config, lines, start, end, frame_id, *, check=lambda:None):
    """Additional OCR runs only for bounded, syntactically complete code candidates."""
    from PIL import Image
    candidates = []
    for indices in groups(lines):
        if len(candidates) >= MAX_BLOCKS:
            break
        selected = [lines[i] for i in indices]
        try:
            code = reading(selected, confidence=(55, 80))
        except (ValueError, KeyError, TypeError):
            continue
        box = [min(r["bbox"][0] for r in selected), min(r["bbox"][1] for r in selected),
               max(r["bbox"][2] for r in selected), max(r["bbox"][3] for r in selected)]
        candidates.append((indices, selected, code, box))
    if not candidates:
        return [], set()
    source_hash = digest_file(image)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    accepted, consumed = [], set()
    for indices, first, code, box in candidates:
        check()
        binding = {"policy": POLICY, "frame_sha256": source_hash, "bbox": box,
                   "first_reading": signature(first), "runtime": config,
                   "code_readings":{"languages":"eng", "psm":[6,3], "confidence":"word-80-block-90"}}
        receipt = folder/(signature(binding)+".json")
        try:
            if receipt.exists():
                saved = read(receipt)
                if (saved.get("binding") != binding or saved.get("payload_hash") !=
                        signature({k:v for k,v in saved.items() if k != "payload_hash"})):
                    raise ValueError("VIDEO_CODE_CACHE_CHANGED")
                second = saved["second_reading"]
                third = saved["third_reading"]
            else:
                crop = folder/(signature(binding)+".png")
                with Image.open(image) as im:
                    x1,y1,x2,y2 = [v*s/1000 for v,s in zip(box,[im.width,im.height,im.width,im.height])]
                    padding = max(12, round((y2-y1)/max(1,len(first))))
                    # Include a whitespace boundary, never crop off a symbol or stitch frames.
                    bounds = (max(0,math.floor(x1)-padding), max(0,math.floor(y1)-padding),
                              min(im.width,math.ceil(x2)+padding), min(im.height,math.ceil(y2)+padding))
                    im.crop(bounds).save(crop)
                second = local_ocr.recognize(crop, folder/"second-ocr", {**config, "languages":"eng", "psm":6})
                third = local_ocr.recognize(crop, folder/"third-ocr", {**config, "languages":"eng", "psm":3})
                saved = {"binding":binding, "second_reading":second, "third_reading":third, "crop_sha256":digest_file(crop)}
                saved["payload_hash"] = signature(saved)
                save(receipt, saved)
            if code_tokens(reading(second)) != code_tokens(code) or code_tokens(reading(third)) != code_tokens(code):
                continue
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
            # Original OCR records remain held; no fuzzy correction or partial acceptance.
            continue
        check()
        proof = {"policy":POLICY, "source_image_sha256":source_hash, "bbox":box,
                 "code_sha256":signature(code), "first_reading_sha256":signature(first),
                 "second_reading_sha256":signature(second), "receipt_sha256":digest_file(receipt),
                 "third_reading_sha256":signature(third),
                 "syntax_checked":True, "execution_verified":False}
        accepted.append({"id":frame_id+"-code-"+signature(code)[:12], "modality":"visual",
                         "text":"\x60\x60\x60python\n"+code+"\n\x60\x60\x60", "bbox":box, "code_block":proof,
                         "start_seconds":start, "end_seconds":end, "isolated":True,
                         "source_locator":f"영상 {start:.1f}–{end:.1f}초 · Python 코드",
                         "reasons":[], "eligible_for_chunking":True})
        consumed.update(indices)
    if digest_file(image) != source_hash:
        raise ValueError("SOURCE_CHANGED")
    return accepted, consumed


def valid_record(record):
    proof = record.get("code_block") or {}
    text = record.get("text", "")
    match = re.fullmatch(r"\x60\x60\x60python\n(.*?)\n\x60\x60\x60", text, re.S)
    return bool(match and proof.get("policy") == POLICY and proof.get("syntax_checked") is True
                and proof.get("execution_verified") is False
                and proof.get("code_sha256") == signature(match[1]) and syntax_checked(match[1])
                and all(re.fullmatch(r"[0-9a-f]{64}", str(proof.get(k,""))) for k in (
                    "source_image_sha256", "first_reading_sha256", "second_reading_sha256", "third_reading_sha256", "receipt_sha256")))

