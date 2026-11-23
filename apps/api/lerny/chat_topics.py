"""Bounded, local topic checks for conversational retrieval."""

import re
import unicodedata


WORDS = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*|[가-힣]+|\d+")
IDENTIFIER = re.compile(r"`([a-z_]\w*)`|(?<![a-z0-9_])([a-z_][a-z0-9_]*)\s*\(", re.I)
DEICTIC = re.compile(
    r"(?:왜(?:\s*그런(?:가요|거야|데요|지))?|"
    r"(?:(?:이|그)\s*(?:부분|내용|거|것)\s*)?(?:좀\s*)?(?:더\s*)?"
    r"(?:쉽게|자세히|간단히|다르게)(?:\s*(?:말|설명|풀어)\s*(?:해)?\s*(?:줘|주세요))?)"
    r"[\s?？.!]*"
)
PARTICLE = re.compile(r"(?:에서는|으로는|이란|이랑|에서|으로|에게|처럼|까지|은|는|이|가|을|를|와|과|의|로)$")
REQUEST = re.compile(
    r"(?:예시|예제|예|사례|이유|원리|의미|방법|차이|뜻|질문|내용|부분|거|것|그거|이거|그것|이것|"
    r"예를|들어|들어서|들어줘|들어주세요|들면|그|이|이걸|그걸|좀|조금|더|다시|쉽게|간단히|자세히|왜|어떻게|뭐|뭔지|"
    r"(?:뭐|무엇|왜)(?:야|지|죠|예요|에요|인가요|일까|일까요)?|"
    r"(?:설명|정리|비교|보여|알려|말|풀어)(?:해|하여|해서|해줄|주실|줄|주|줘|줘요|주세요|줄래|줄래요|줄까요|해줘|해주세요|해줘요|하나요|해줄래요)?|"
    r"한다면|한번|하나만|하나|대해|대한|주세요|줘|해줘|해|인가요|인가|일까요|있어|있나요|수|있을까요|"
    r"what|why|how|is|it|a|an|the|me|give|show|explain|example[s]?|again|please|"
    r"can|you|more|simply|simpler|that|this|does|do|mean)", re.I
)
ALIASES = {
    "upper": ("대문자", "uppercase", "upper case"),
    "lower": ("소문자", "lowercase", "lower case"),
    "len": ("길이", "length"),
    "print": ("출력",),
    "stack": ("스택",),
    "queue": ("큐",),
}
EXAMPLE_REQUEST = re.compile(r"예시|예제|예를\s*들|사례|\bexamples?\b", re.I)
EXAMPLE_EVIDENCE = re.compile(
    r"(?:예시|예제|사례|예|\bexamples?)\s*[:：]\s*\S|(?:예시|예제)[ \t]*\n\s*\S|"
    r"(?:예를\s*들어|예를\s*들면|가령|for example|\be\.g\.)[,\s]+\S|"
    r">>>|→|=>|->|"
    r"(?:['\"\]\)]\s*\.\s*\w+\s*\(|\b\w+\s*\(\s*['\"\d\[\{])|"
    r"입력.{0,60}출력", re.I | re.S
)


def topic_terms(question):
    text = unicodedata.normalize("NFKC", question).casefold()
    if DEICTIC.fullmatch(text.strip()):
        return []
    identifiers = {name or call for name, call in IDENTIFIER.findall(text)}
    terms = []
    for word in WORDS.findall(text):
        stem = PARTICLE.sub("", word)
        if word not in identifiers and (not stem or REQUEST.fullmatch(word) or REQUEST.fullmatch(stem)):
            continue
        term = stem if len(stem) >= 2 or stem in {"큐", "힙", "맵", "셋"} else word
        if term not in terms:
            terms.append(term)
    specific = [t for t in terms if t not in {"함수", "메서드", "변환", "기능", "코드", "사용법", "문법"}]
    return specific or terms


def mentions_topic(text, terms):
    text = unicodedata.normalize("NFKC", text).casefold()
    for term in terms:
        variants = next(((key, *aliases) for key, aliases in ALIASES.items()
                         if term in (key, *aliases)), (term,))
        for variant in variants:
            if variant.isascii():
                if re.search(r"(?<![a-z0-9_])" + re.escape(variant) + r"(?![a-z0-9_])", text):
                    return True
            elif variant in text:
                return True
    return False


def previous_topic(history, context):
    """Use the most recent named subject, including across consecutive follow-ups."""
    citations = None
    for message in history:
        prev = message.learning_context or {}
        if (prev.get("mode", "theory"), prev.get("exercise_id")) != (
                context.get("mode", "theory"), context.get("exercise_id")):
            break
        answer = message.answer or {}
        terms = topic_terms(message.question)
        # A legacy generic turn may itself have been grounded on an unrelated slide.
        if (citations is None and answer.get("answer_kind") == "grounded"
                and (terms or answer.get("validation") == "citation_checked")):
            citations = [c.get("chunk_id") or c["source_id"] for c in answer.get("citations", [])
                         if c.get("chunk_id") or c.get("source_id")]
        if terms:
            return terms, list(dict.fromkeys(citations or []))[:6]
    return [], []
