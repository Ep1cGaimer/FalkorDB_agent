"""Trusted check that a proposal is grounded in what the operator actually identified (issue #17).

`propose_fleet` must list `request_references`: the exact phrases of the operator's own words that
identify what to undo or keep. Trusted code then decides, without asking the model, whether those
phrases pin down a change:

- Each phrase must be verbatim text the operator wrote (the original request or the operator's
  clarification answer), never the agent's own question.
- Together they must cover every meaningful word of the original request, so a vague part
  ("from last week") cannot simply be left out.
- A phrase that names a change ("change", "update", "build", a relative time such as "last week")
  but contains no concrete anchor (a behavior word such as "basket", or a version such as "1.4") is
  unresolved. Service names alone are scope, not anchors.

An operator answer that itself contains an anchored phrase resolves the original request's vague
phrases. The check is lexical and deliberately generic: it uses no fixture names, versions, dates or
expected answers. It cannot prove the model bound an anchored phrase to the right artifact; the
citation and checker steps cover that.
"""
from __future__ import annotations

import re

QUESTION_MARK = "\n\nAgent asked: "
ANSWER_MARK = "\nOperator answered: "

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")

# Grammar, rollback verbs and non-committal answer words: never an anchor, never need coverage.
STOPWORDS = frozenset("""
a an the this that these those it its it's of to from in on off at by for with into onto and or but
not no yes so as than then there here what which who whom whose when where while if is are was were
be been being do does did done has have had having will would can could should may might must
i we you they he she me us our my your their his her them
please just only also again back roll rolled rollback rollbacks undo undone revert reverted restore
restored keep kept turn turned disable disabled enable enabled remove removed go went put return
ran run running use used using want need make made
know sure unsure idk remember think guess maybe whatever any anything something some don t didn
isn wasn can't cannot
""".split())

# A relative time or a generic change noun marks a phrase as naming a change, but anchors nothing.
TIME_TERMS = frozenset("""
last past previous prior recent recently earlier ago latest newest current new old older before after
today yesterday tonight tomorrow week weeks weekend month months day days night morning afternoon
evening hour hours minute minutes year years monday tuesday wednesday thursday friday saturday sunday
""".split())
GENERIC_NOUNS = frozenset("""
change changes changed update updates updated release releases released build builds deploy deploys
deployed deployment deployments version versions patch patches commit commits push pushed rollout
rollouts feature features fix fixes fixed correction corrections thing things stuff one ones work
""".split())


def _words(text: str) -> list[tuple[str, int, int]]:
    """Lower-cased word tokens with their character spans (versions such as 1.4 stay one token)."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text.lower())]


def operator_texts(request_text: str) -> tuple[str, str | None]:
    """(original request, operator answer or None), split off the agent's question.

    `pipeline.with_answer` builds "<request>\\n\\nAgent asked: <question>\\nOperator answered: <answer>".
    The answer is taken after the LAST answer marker, so a model-authored question can never inject
    text that is treated as the operator's.
    """
    if QUESTION_MARK in request_text and ANSWER_MARK in request_text:
        original = request_text.split(QUESTION_MARK, 1)[0]
        answer = request_text.rsplit(ANSWER_MARK, 1)[1]
        return original, answer
    return request_text, None


def is_anchored(phrase: str, services: set[str]) -> bool:
    """A phrase anchors a change when some word is not grammar, time, a generic noun or a service."""
    return any(w not in STOPWORDS and w not in TIME_TERMS and w not in GENERIC_NOUNS and w not in services
               for w, _, _ in _words(phrase))


def names_a_change(phrase: str) -> bool:
    """Whether a phrase refers to a change at all (a service name alone is only scope)."""
    return any(w in TIME_TERMS or w in GENERIC_NOUNS for w, _, _ in _words(phrase))


def check_references(references: object, request_text: str, services: set[str]) -> list[str]:
    """Validation errors for a proposal's `request_references`; empty when the request is grounded."""
    services = {s.lower() for s in services}
    if not isinstance(references, list) or not references \
            or not all(isinstance(r, str) and r.strip() for r in references):
        return ["INTENT_REFERENCES_MISSING: list request_references, the exact phrases of the operator's "
                "request that identify what to undo and what to keep"]
    original, answer = operator_texts(request_text)
    errors: list[str] = []
    original_spans: list[tuple[int, int]] = []
    answer_phrases: list[str] = []
    original_phrases: list[str] = []
    lowered_original, lowered_answer = original.lower(), (answer or "").lower()
    for phrase in references:
        # Whole words only: a fragment such as "kno" inside "know" is not something the operator said.
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(phrase.strip().lower()) + r"(?![a-z0-9])")
        matches = [(m.start(), m.end()) for m in pattern.finditer(lowered_original)]
        if matches:
            original_phrases.append(phrase)
            original_spans.extend(matches)
        elif answer and pattern.search(lowered_answer):
            answer_phrases.append(phrase)
        else:
            errors.append(f"INTENT_REFERENCE_NOT_OPERATOR_TEXT: {phrase!r} is not verbatim text the operator "
                          "wrote (the agent's own question does not count)")
    uncovered = sorted({w for w, s, e in _words(original) if w not in STOPWORDS
                        and not any(a <= s and e <= b for a, b in original_spans)})
    if uncovered:
        errors.append("INTENT_REFERENCE_INCOMPLETE: request_references must cover every part of the "
                      f"operator's request; not covered: {uncovered}")
    answered = any(is_anchored(p, services) for p in answer_phrases)
    if not answered:
        for phrase in original_phrases:
            if names_a_change(phrase) and not is_anchored(phrase, services):
                errors.append(f"INTENT_UNRESOLVED: {phrase!r} does not identify one specific change; call "
                              "ask_clarification and ask which change or release the operator means")
    return errors
