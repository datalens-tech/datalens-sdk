# Lakehouse entry ID execution tracker

Base: fresh origin/main 6e693fa. Worktree: lakehouse-entry-id.

[X] Stage 1: RPC schema downloaded and compared; identifier wire fields unchanged.
[X] Stage 2: Fixtures updated to entry identity; error regression observed failing.
[X] Stage 3: Model semantics, validation messages and schema descriptions updated.
[X] Stage 4: End-to-end regressions and focused verification.
[X] Stage 5: Skill migration and artifact verification.
[X] Stage 6: Full gate and final review.

Ruling: Keep this change scoped to identity; downloaded unrelated API additions are excluded.
Ruling: User requires all work in the new public worktree; private generation and joint checks that mutate the original workspace are omitted.
Ruling: Existing public entry_id fields remain response metadata; no compatibility resolver or old-ID support is introduced.

Verification: 440 focused tests passed; final navigation additions passed (388 tests).
Verification: generated-check, lint, format-check, format-json-check, artifacts-check passed.
Verification: mypy initially caught context-manager type widening in new tests; fixed and passed (281 files).
Final review: independent reviewer found no important issues; stale test name corrected.

Final verification: 3689 tests passed on each Python 3.10, 3.11, 3.12, 3.13 and 3.14; dependency-lower-bounds also passed (3689 tests).
Full gate initially exited 1 for the new tests context-manager typing; the corrected typecheck passed separately, as did final lint and format-check.
Joint private checks deliberately not run: user restricted all work to this new public worktree.
