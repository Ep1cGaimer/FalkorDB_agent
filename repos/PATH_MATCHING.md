# Exact source-corpus path profiles

`RepoConfig.path_matching` explicitly selects the glob convention:

| Value | Behaviour |
|---|---|
| `path_or_basename` | Default, preserving existing configurations: match a full repository-relative path or its basename. A `setup.py` include therefore also matches `nested/setup.py`. |
| `path` | Match only the full repository-relative path. A root `setup.py` rule admits only that path. |

Both profiles use case-sensitive `fnmatch`; `*` can cross `/`, and exclusions win.
The selected profile applies to include, exclude and release-note patterns.

`regular_files_only` is a strict boolean, default `false`. Setting it to `true`
admits only regular Git blob modes `100644` and `100755`. Other changed blob modes
are reported as coverage exclusions. Submodules are never implicitly fetched and
symlinks are never dereferenced. Excluding content does not establish that code or
dependencies are absent there. Source-only corpus exports retain excluded-path
and symlink metadata for explicit coverage reporting.

Changing either option invalidates stored file maps on the next normal import.
`evals/confirmatory/graph_tools.config_for_export` uses `path` and
`regular_files_only=true`, plus the export's exact roots/rules/eligible tags. Its
readiness check compares all historical source memberships and ordered parents to
the raw export before any question generation. This is corpus equality checking,
not proof of answer quality or comparative benefit.

These newer options are documented separately because the independently authored
draft protocol hashes the earlier `repos/README.md` bytes. That historical
dependency remains unchanged; the final protocol must independently review the
new implementation/configuration before freeze.
