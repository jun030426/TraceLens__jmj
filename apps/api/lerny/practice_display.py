"""Student editor coordinates. Grading source and saved UTF-16 spans use raw coordinates."""
import re


def leading_blank_lines(source):
    prefix = re.match(r"(?:[^\S\n]*\n)*", source)
    return prefix.group().count("\n")


def example_declaration(source):
    lines = source.split("\n")[leading_blank_lines(source):]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).removesuffix("\r")


def editor_source(source, kind, language, snapshot=None):
    """All blank fills are single-line, so this projection also applies after substitution."""
    if kind == "blank" and language == "python":
        removed = leading_blank_lines(source)
        return source.split("\n", removed)[-1], -removed
    # Full submissions are historically stripped before grading. New snapshots remember
    # how many editor lines that removed, without changing the worker's input.
    restored = (snapshot or {}).get("editor_leading_lines", 0) if kind == "full" else 0
    return "\n" * restored + source, restored


def attempt_display(attempt, kind, language):
    source, offset = editor_source(attempt.source, kind, language, attempt.submission_snapshot)
    if not offset:
        return {"feedback": attempt.feedback}

    def message(value):
        if not isinstance(value, str):
            return value
        return re.sub(r"^(\d+)(?=번째 줄)", lambda m: str(max(1, int(m[1]) + offset)), value)

    feedback = attempt.feedback
    if feedback:
        feedback = {**feedback, "message": message(feedback.get("message"))}
        syntax = feedback.get("syntax")
        if syntax and isinstance(syntax.get("error_line"), int):
            feedback["syntax"] = {**syntax, "error_line": max(1, syntax["error_line"] + offset),
                                  "error_message": message(syntax.get("error_message"))}
    return {"feedback": feedback, "replay_source": source}
