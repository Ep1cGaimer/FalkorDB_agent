# Raw Git ancestry and graft recovery

Commit `f8faa67` closes an additional revision-integrity defect found during
development while the independent clean environment was being prepared. No
held-out question or answer informed this repair.

A local `.git/info/grafts` file could make a genuine child appear parentless or
skip an intermediate commit. Disabling replacement objects did not disable this
separate ancestry overlay. A direct reproduction showed `is_ancestor` returning
false for a parent recorded in the immutable commit object and history import
omitting that parent. Git's [environment definitions](https://github.com/git/git/blob/master/environment.h)
identify the separate `GIT_GRAFT_FILE` control.

The hardened read environment now points that control to the null device. Two
regressions derive the true parents with `git cat-file`, inject the two overlay
forms, and check history enumeration, ancestry, first-parent changes, actual graph
parent edges and source-backed access to the intermediate revision.

A second regression exposed a recovery issue: parent facts were only written for
commits whose file maps were new. Retrying an old completed import could therefore
retain an incorrect parent edge. Import now refreshes discovered commit metadata
and replaces its parent edges independently of unchanged file-map/blob reuse.
Publication remains unavailable during mutation, and every write retains the lease
ownership check. The regression leaves a stale parent on an already completed
commit, retries the normal import command, and checks the exact true parent.

Observed attempts, retained separately:

| Attempt | Observed result |
|---|---|
| Initial two graft regressions | 2 failed |
| Environment fix with history/recovery/generated/canary checks | 136 passed, 106.42 s |
| Stale-parent retry regression before import repair | 1 failed |
| Intermediate import edit omitted the file-map `todo` variable | 3 failed, 34 setup errors; variable restored |
| Final graft/history/recovery/lease subset | 37 passed, 22.80 s |

The [168-file manifest](goal-graft-evidence/implementation-manifest.json) pins the
new implementation and configuration bytes. The independent reviewer switched its
clean clone to this commit before running tests and verified every hash. Its full
reproduction result is separate; none of the focused results validates T0–T11 or
establishes comparative advantage.

Evidence: [final subset](goal-graft-evidence/git-grafts-final-002.xml),
[initial failures](goal-graft-evidence/git-grafts-baseline.xml), and
[stale-parent failure](goal-graft-evidence/git-grafts-recovery-baseline.xml).
