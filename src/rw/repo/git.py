"""Read-only git access via plumbing (git -C <path> ...). Never checks out or touches the index."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: list[str]
    author_time: int
    subject: str
    message: str


@dataclass(frozen=True)
class Tag:
    name: str
    target_sha: str
    message: str


@dataclass(frozen=True)
class Change:
    status: str  # A M D R
    old_path: str | None
    new_path: str | None
    similarity: int | None = None


class GitError(RuntimeError):
    pass


class GitRepo:
    def __init__(self, path: str | Path):
        self.path = str(Path(path))

    def _proc(self, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
        from rw.repo.budget import BudgetExhausted, active_budget
        budget = active_budget()
        try:
            proc = subprocess.run(self._command(*args), capture_output=True,
                                  env=self._environment(), input=stdin,
                                  timeout=budget.remaining() if budget else None)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for the child before raising.
            if budget:
                raise BudgetExhausted(budget, "seconds") from None
            raise
        if budget:
            budget.remaining()
        return proc

    def _environment(self) -> dict[str, str]:
        # Do not let the caller's Git routing/configuration select a different object database,
        # invoke a pager, or replace objects. Repository-local configuration still applies, so
        # executable Git features are also disabled explicitly in _command.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
                   GIT_GRAFT_FILE=os.devnull, GIT_PAGER="cat")
        return env

    def _command(self, *args: str) -> list[str]:
        return ["git", "--no-pager", "-c", "core.quotepath=false",
                "-c", "log.showSignature=false", "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=" + os.devnull, "-c", "diff.external=",
                "-c", "core.pager=cat", "-C", self.path, *args]

    def _bytes(self, *args: str, stdin: bytes | None = None) -> bytes:
        proc = self._proc(*args, stdin=stdin)
        if proc.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace').strip()}")
        return proc.stdout

    def _text(self, *args: str) -> str:
        return self._bytes(*args).decode("utf-8", "replace")

    def resolve(self, rev: str) -> str:
        if not rev or rev.startswith("-"):
            raise GitError(f"invalid revision {rev!r}")
        return self._text("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()

    def commits(self, revs: list[str]) -> list[Commit]:
        """All commits reachable from `revs`, parents before children."""
        shas = [self.resolve(r) for r in revs]
        if not shas:
            return []
        out = self._text("log", "--no-show-signature", "--topo-order", "--reverse",
                         "--format=%H%x00%P%x00%at%x00%s%x00%B%x1e", *shas, "--")
        result = []
        for rec in out.split("\x1e"):
            rec = rec.lstrip("\n")
            if not rec:
                continue
            sha, parents, at, subject, body = rec.split("\x00", 4)
            result.append(Commit(sha, parents.split(), int(at), subject, body.rstrip("\n")))
        return result

    def tags(self) -> list[Tag]:
        fmt = "%(refname:strip=2)%00%(objectname)%00%(objecttype)%00%(contents)%1e"
        tags = []
        for rec in self._text("for-each-ref", "refs/tags", f"--format={fmt}").split("\x1e"):
            rec = rec.lstrip("\n")
            if not rec:
                continue
            name, _obj, otype, contents = rec.split("\x00", 3)
            try:
                target = self.resolve(f"refs/tags/{name}")  # peels annotated (and nested) tags
            except GitError:
                continue  # tag of a tree/blob: not a revision
            tags.append(Tag(name, target, contents.strip() if otype == "tag" else ""))
        return tags

    def tree(self, sha: str) -> list[tuple[str, str, str]]:
        items = []
        for entry in self._text("ls-tree", "-r", "-z", "--full-tree", sha).split("\x00"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            mode, otype, osha = meta.split()
            if otype == "blob":
                items.append((path, osha, mode))
        return items

    def blob(self, sha: str) -> bytes:
        from rw.repo.budget import active_budget
        budget = active_budget()
        if budget:
            # Object identity is immutable: inspect its size before fetching payload.
            # RepoQuery charges the actual returned bytes after fetching.
            budget.check_source(self._blob_size(sha))
        return self._bytes("cat-file", "blob", sha)

    def _blob_size(self, sha: str) -> int:
        value = self._text("cat-file", "-s", sha).strip()
        if not value.isdecimal():
            raise GitError("invalid Git object size")
        return int(value)

    def _reserve_patch_sources(self, child: str, parent: str | None = None) -> None:
        """Bound raw diff inputs before Git reads them; account a conservative reservation.

        Metadata is read without source payload. Old/new changed blobs are charged
        per path, including repeated objects, so this cannot undercount reused inputs.
        A failed diff retains its reservation. No reservation applies during indexing,
        which runs outside request read scopes.
        """
        from rw.repo.budget import active_budget
        budget = active_budget()
        if not budget:
            return
        revisions = (parent, child) if parent is not None else ("--root", child)
        records = self._text("diff-tree", "-r", "--raw", "-z", "--no-abbrev", "--no-renames",
                             "--no-commit-id", *revisions).split("\0")
        total, sizes = 0, {}
        for record in records[::2]:
            if not record:
                continue
            fields = record.lstrip().removeprefix(":").split()
            if len(fields) != 5:
                raise GitError("invalid raw diff metadata")
            old_mode, new_mode, old, new, _status = fields
            for mode, oid in ((old_mode, old), (new_mode, new)):
                if mode not in {"100644", "100755", "120000"} or set(oid) == {"0"}:
                    continue
                if oid not in sizes:
                    sizes[oid] = self._blob_size(oid)
                total += sizes[oid]
                budget.check_source(total)
        budget.consume_source(total)

    def changes(self, parent: str, child: str) -> list[Change]:
        parts = self._text("diff-tree", "-r", "-M", "-z", "--name-status", "--no-commit-id",
                           parent, child).split("\x00")
        changes, i = [], 0
        while i < len(parts):
            st = parts[i]
            if not st:
                i += 1
                continue
            code = st[0]
            if code in "RC":
                old, new = parts[i + 1], parts[i + 2]
                sim = int(st[1:]) if st[1:].isdigit() else None
                changes.append(Change("R", old, new, sim) if code == "R" else Change("A", None, new, sim))
                i += 3
                continue
            p = parts[i + 1]
            if code == "A":
                changes.append(Change("A", None, p))
            elif code == "D":
                changes.append(Change("D", p, None))
            else:  # M, T
                changes.append(Change("M", p, p))
            i += 2
        return changes

    def is_ancestor(self, a: str, b: str) -> bool:
        proc = self._proc("merge-base", "--is-ancestor", a, b)
        if proc.returncode not in (0, 1):
            raise GitError(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode == 0

    def patch(self, parent: str, child: str) -> str:
        """Unified diff (no context, renames detected) of child against parent."""
        self._reserve_patch_sources(child, parent)
        return self._text("diff-tree", "-p", "-M", "-U0", "--no-color", "--no-ext-diff",
                          "--no-textconv", "--no-commit-id", parent, child)

    def patch_id(self, sha: str) -> str | None:
        """`git patch-id --stable` of a commit against its first parent (None for root/empty)."""
        self._reserve_patch_sources(sha)
        diff = self._bytes("diff-tree", "-p", "--no-color", "--no-ext-diff", "--no-textconv",
                           "--root", sha)
        out = self._bytes("patch-id", "--stable", stdin=diff).decode("utf-8", "replace").split()
        return out[0] if out else None

    # ------------------------------------------------------------ bulk access (indexing large histories)
    def first_parent_changes(self, revs: list[str]):
        """Yield (sha, [(status, path, blob_sha, mode)]) for every commit reachable from `revs`
        (parents before children), diffing each commit against its FIRST parent (root: empty tree).
        One `git log --raw` process for the whole history; renames are reported as D + A."""
        shas = [self.resolve(r) for r in revs]
        if not shas:
            return
        out = self._bytes("log", "--no-show-signature", "--no-ext-diff", "--no-textconv",
                          "--topo-order", "--reverse", "--raw", "-z", "--no-abbrev",
                          "--no-renames", "--diff-merges=first-parent", "--root",
                          "--format=%x01%H", *shas, "--")
        for chunk in out.split(b"\x01"):
            if not chunk:
                continue
            parts = chunk.split(b"\x00")
            sha = parts[0].decode().strip()
            changes, i = [], 1
            while i < len(parts):
                meta = parts[i].lstrip(b"\n")
                if not meta.startswith(b":"):
                    i += 1
                    continue
                _m1, m2, _s1, s2, st = meta[1:].decode().split(" ")
                path = parts[i + 1].decode("utf-8", "replace")
                changes.append((st[0], path, s2, m2))
                i += 2
            yield sha, changes

    def blob_batch(self, shas):
        """Yield (sha, bytes) for each blob sha via one `git cat-file --batch` process (streamed)."""
        import threading
        shas = list(shas)
        if not shas:
            return
        proc = subprocess.Popen(self._command("cat-file", "--batch"), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self._environment())

        def feed():
            try:
                for s in shas:
                    proc.stdin.write(f"{s}\n".encode())
                proc.stdin.close()
            except OSError:
                pass
        t = threading.Thread(target=feed, daemon=True)
        t.start()
        try:
            for s in shas:
                header = proc.stdout.readline().split()
                if len(header) < 3 or header[1] == b"missing":
                    raise GitError(f"git cat-file: missing object {s}")
                size = int(header[2])
                data = proc.stdout.read(size)
                proc.stdout.read(1)  # trailing LF
                yield s, data
        finally:
            proc.stdout.close()
            proc.kill() if proc.poll() is None else None
            proc.wait()
            t.join(timeout=5)
