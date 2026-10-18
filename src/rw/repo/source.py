"""Physical source lines for Git spans, hashes, patches and release notes.

LF delimits a source line. CR immediately before LF is a line ending too;
Unicode/control separators inside a line remain source content. A terminal LF
does not create a fictitious extra line. Full-file content hashes use raw bytes.
"""

LINE_SCHEMA = "physical-lf-v1"


def source_lines(text: str) -> list[str]:
    parts = text.split("\n")
    ended = text.endswith("\n")
    if ended:
        parts.pop()
    if not text:
        return []
    return [part[:-1] if part.endswith("\r") and (i < len(parts) - 1 or ended) else part
            for i, part in enumerate(parts)]
