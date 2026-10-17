"""Trusted check that a rollback request identifies the change it asks for (issue #17).

Trusted code, not the model, splits the operator's request into clauses (on punctuation and on
joining words such as "and" and "but") and requires every clause that asks to undo or change
something to carry a concrete anchor: a word that is not grammar, a rollback verb, a relative time,
a generic change noun ("change", "update", "build", ...) or a service name. "Roll back the cart
change from last week." and "Undo it." have no anchor and are unresolved; "Undo the basket
rollout, but keep the receipt correction." and "Roll cart back to 1.4" are not.

An operator answer to the agent's question resolves an unresolved request only when it carries an
anchor and no negation or uncertainty ("no idea", "I'm not sure" do not). Only operator-authored
text counts: the original request and the operator's answer, never the agent's question.

The check is lexical and deliberately generic: no fixture names, versions, dates or expected answers.
It cannot show that an anchored request was bound to the right artifact; that interpretation remains
the model's (and the operator's, who confirms scope). Citations and the checker do not prove it.
"""
from __future__ import annotations

import re

QUESTION_MARK = "\n\nAgent asked: "
ANSWER_MARK = "\nOperator answered: "

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")
_CONTRACTIONS = {"n't": " not", "'m": " am", "'re": " are", "'s": " is", "'ve": " have", "'ll": " will",
                 "'d": " would"}
_CLAUSE_BREAK = re.compile(r"[,;:.!?\n()\[\]]+|\b(?:and|but|while|whereas|except|then|also|plus|or)\b")

# Grammar and filler: never an anchor.
STOPWORDS = frozenset("""
a an the this that these those it its of to from in on off at by for with into onto as than there here
what which who whom whose when where if is are am was were be been being do does did done has have had
having will would can could should may might must shall i we you they he she me us our my your their
his her them please just only so too very really still now already
""".split())
# Asking to undo or change something: never an anchor, and marks a clause as needing one.
ACTION_WORDS = frozenset("""
undo undone roll rolled rolling rollback back revert reverted reverting restore restored disable
disabled remove removed drop dropped turn turned switch switched go went return put get bring pull
redeploy deploy downgrade reset change replace swap fix ran run running use used using want need make
made keep kept leave left retain preserve stay enable enabled
""".split())
# A relative time or a generic change noun: marks a clause as naming a change, anchors nothing.
TIME_TERMS = frozenset("""
last past previous prior recent recently earlier ago latest newest current new old older before after
today yesterday tonight tomorrow week weeks weekend month months day days night morning afternoon
evening hour hours minute minutes year years monday tuesday wednesday thursday friday saturday sunday
""".split())
GENERIC_NOUNS = frozenset("""
change changes changed update updates updated release releases released build builds deploys deployed
deployment deployments version versions patch patches commit commits push pushed rollout rollouts
feature features fixes fixed correction corrections thing things stuff one ones work code
""".split())
# In an operator answer, any of these means the operator did not identify the change.
UNCERTAIN = frozenset("""
not no nope never unsure idea know dunno idk maybe perhaps whatever either any anything something guess
think remember sure clue unclear
""".split())


def _normalize(text: str, services: set[str]) -> str:
    """Lower-case, expand contractions, and blank out whole service names (including hyphenated ones)."""
    out = text.lower().replace("’", "'")
    for short, long in _CONTRACTIONS.items():
        out = out.replace(short, long)
    for service in sorted(services, key=len, reverse=True):
        out = re.sub(r"(?<![a-z0-9-])" + re.escape(service.lower()) + r"(?![a-z0-9-])", " ", out)
    return out


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text)


def clauses(text: str, services: set[str]) -> list[list[str]]:
    """The request split into word lists by trusted code, so no model choice can merge a vague clause
    with an unrelated anchored one."""
    return [w for w in (_words(part) for part in _CLAUSE_BREAK.split(_normalize(text, services)) if part) if w]


def _anchors(words: list[str]) -> list[str]:
    return [w for w in words
            if w not in STOPWORDS and w not in ACTION_WORDS and w not in TIME_TERMS and w not in GENERIC_NOUNS]


def operator_texts(request_text: str) -> tuple[str, str | None, bool]:
    """(original request, operator answer or None, well_formed).

    `pipeline.with_answer` builds "<request>\\n\\nAgent asked: <question>\\nOperator answered: <answer>".
    Either marker appearing more than once (in the operator's text or in a model-authored question)
    makes the provenance ambiguous, and the request is then treated as unresolved.
    """
    asked, answered = request_text.count(QUESTION_MARK), request_text.count(ANSWER_MARK)
    if asked == 0 and answered == 0:
        return request_text, None, True
    if asked != 1 or answered != 1 or request_text.index(QUESTION_MARK) > request_text.index(ANSWER_MARK):
        return request_text.split(QUESTION_MARK, 1)[0], None, False
    original, rest = request_text.split(QUESTION_MARK, 1)
    return original, rest.split(ANSWER_MARK, 1)[1], True


def unresolved_clauses(text: str, services: set[str]) -> list[str]:
    """Clauses that ask to undo or change something without a concrete anchor."""
    out = []
    for words in clauses(text, services):
        names_change = any(w in ACTION_WORDS or w in TIME_TERMS or w in GENERIC_NOUNS for w in words)
        if names_change and not _anchors(words):
            out.append(" ".join(words))
    return out


def answer_identifies(answer: str, services: set[str]) -> bool:
    words = [w for part in clauses(answer, services) for w in part]
    return bool(_anchors(words)) and not any(w in UNCERTAIN for w in words)


def check_request(request_text: str, services: set[str] | None) -> list[str]:
    """Errors when the operator's request does not identify the change; empty when it does."""
    if services is None:
        return ["INTENT_UNRESOLVED: the current fleet could not be read, so the request cannot be checked; "
                "call ask_clarification"]
    original, answer, well_formed = operator_texts(request_text)
    if not well_formed:
        return ["INTENT_UNRESOLVED: the request text contains the reserved 'Agent asked:' / 'Operator "
                "answered:' markers more than once; call ask_clarification"]
    vague = unresolved_clauses(original, services)
    if not vague or (answer is not None and answer_identifies(answer, services)):
        return []
    return [f"INTENT_UNRESOLVED: {clause!r} does not identify one specific change; call ask_clarification "
            "and ask which change or release the operator means" for clause in vague]
