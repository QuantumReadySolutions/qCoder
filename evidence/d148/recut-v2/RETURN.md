# D-148 contained TTY correction and preparation recut v2

**Stopped at the new real Rob-origin approval boundary. No canonical held-out
science ran.** This return supersedes the prior dev4 preparation and approval
command; prior evidence remains preserved. No conference/public release or Phase E
claim is made.

## Git and scope

Branch: `conference/iqt-2026-ml-research-successor-v1`.
Starting correction HEAD: `a9be5bcdcc6bda2c89a09a086d302d50e5296455`;
tree `603774868ccac3094799b07d72f851e2adaaa5a2`. Worktree was verified clean.
No applicable AGENTS.md was found.

Committed and pushed production correction / exact artifact source HEAD:
`9249dfa80c5a574c3f385f1f1b346f537e351bef`.
Tree: `4a0c43c2d7bf5a52090c9f59a6867b7c24b52558`.
Parent: `a9be5bcdcc6bda2c89a09a086d302d50e5296455`.
The handoff message gives the final evidence HEAD/tree/parent; this document cannot
embed its own commit hash. No packaged production bytes change after the source commit.

Only the assigned worktree and separate temporary build/install locations were
used. D-147, Tactical_38/WI-0441, protected Stage-D implementation, credentials,
provider operations, owner, existing locks/quotas/counters and review process were
not modified. No WI-0441 file was changed in this correction. No D-147 file was
accessed during this correction; no new fallback hash verification is claimed.
Carbon/Phase E was not started.

## Defect, correction and regression

Rob reported `io.UnsupportedOperation: File or stream is not seekable` from
`open('/dev/tty', 'r+', encoding='utf-8', buffering=1)`. This occurred before
persisted authority or scientific entry. Actual attempt time was not supplied and
is not fabricated. The user report and local absence/hash checks are preserved in
[real-approval-failure.json](real-approval-failure.json).

Production now uses `os.open` with O_RDWR, O_NOCTTY and O_CLOEXEC; validates
S_ISCHR/isatty and foreground process-group ownership; writes at most 2048 prompt
bytes with bounded partial-write handling; reads at most 256 one-byte units to a
newline; rejects EOF, oversized input and any nonexact response; rechecks foreground
ownership and exact plan currentness; persists the same self-digesting approval
schema; closes the descriptor in finally. There is no digest/token command argument,
chat assent path, approval minting in run, or scientific retry change.

Eight regression cases execute the production approval CLI on a genuine controlling
PTY. Every case proves the descriptor is a foreground character device, proves
non-seekability with ESPIPE, and reproduces the old text-update exception before
exercising the corrected path. Exact and fragmented exact input succeeds only on
synthetic test plans. Generic assent, digest-only input, wrong challenge, oversized
input, EOF and plan mutation during input refuse without scientific entry.
Automated PTY input is explicitly test-only; it is not Rob's canonical authority.
Neither old nor new installed production files were patched.

- Source suite: **156 passed**, 8 warnings, 71.97 seconds.
- Clean installed suite: **46 passed**, 8 warnings, 80.17 seconds.
- Initial targeted real-PTY regression: **8 passed**, 38 deselected.
- Python emits a test-process forkpty deprecation warning; each child immediately
  execs a fresh interpreter. No child hung and all PTY cases passed.
- The initial broader source run had **155 passed / 1 failed** because isolated
  child Python ignored PYTHONDONTWRITEBYTECODE and generated source caches. The
  exact source inventory correctly rejected bytecode. The harness now explicitly
  sets sys.dont_write_bytecode before source import; only generated caches were
  removed and the full affected suite passed.
- [Updated failed/superseded attempt ledger](../attempts.json): entries 9–13 retain
  the failed real approval, contained harness correction and successful recut.

Exact commands:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/ml_research/test_d148.py -k real_nonseekable
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/ml_research tests/test_release_version_consistency.py tests/test_focused_loop_contracts_v1.py tests/test_focused_loop_package_isolation_v1.py tests/test_public_package_metadata.py
/tmp/d148-installed-proof-v2/venv/bin/python -I -B -m pytest -q -c /dev/null /tmp/d148-installed-proof-v2/tests/test_d148.py
```

Installed tests ran outside source with no repository pytest configuration.
Synthetic model evaluation/failure/reuse tests remain separate from canonical
science. Source and installed logs are [source-tests.txt](source-tests.txt) and
[installed-tests.txt](installed-tests.txt).

## Preserved old preparation

Old plan: `fcd115f49d3726c3a782725a4872a63e886295153a11a5c168d21f11ef25c9fc`.
Old candidate run: `5a8fbc24aa6845ceb08d1150ac495683`.
Old baseline run: `c285ceb957b84ef49e475f37c5931d12`.
Old assessment run: `9f820359e11b478b8fbb0bcc19305c90`.

The entire old canonical workspace, including SQLite/artifact files and old plan,
was SHA-256 compared before and after recutting and is unchanged. Old wheel/sdist
hashes are unchanged. All 156 old installed payload files still match the old wheel.
Old checkpoints are explicitly rejected by the corrected production validator with
`checkpoint_code_runtime`; that strict check was not weakened. See
[preservation-proof.json](preservation-proof.json) and
[tty-regression-source.json](tty-regression-source.json).

## Unchanged science and exact deterministic comparison

Preparation was rerun from the fresh installed artifact in
`artifacts/d148/canonical-v2`, using byte-for-byte copies of the exact old fixture,
train/validation/test partitions and frozen recipes. No dataset regeneration,
held-out metric computation, hyperparameter/seed selection or threshold change.
The training code, architectures, fixture logic, runtime pins and recipes are unchanged.

Both roles: Adam, lr 0.03, 80 epochs, full batch 120, no shuffle, float64,
minimum validation BCE, earliest exact tie. Candidate seed 161803; baseline seed
141421. Both again select epoch 80. Candidate validation BCE
0.28894970554781835; baseline validation BCE
0.21865491103578596.

**Both roles have exactly identical canonical numeric parameter bytes and complete
80-epoch train/validation history bytes.** All fields outside `training_code` and
`digest` are byte-identical, including recipes, preprocessing/split identities,
selected epoch and runtime. The only changed code file in checkpoint provenance is
`job.py`. Full comparison and digests: [deterministic-comparison.json](deterministic-comparison.json).

| Identity | Candidate | Baseline |
| --- | --- | --- |
| Old checkpoint | `3c681713c68f3dd8837db7506a4faef9c83de61ed8f656210b4a24a69d84f472` | `6ea15ff9a817aef3dffce853e0cb901360326804584811d071060a88683ed8d9` |
| New checkpoint | `457897807be1bd9197fc54db66c3488af21cc765e84b5236624b3dd798b070e3` | `9ced20ed5f0919d2a674b7934ecd89d66c720968c91d345d6fd5a7410bf56657` |
| Numeric state SHA-256, old = new | `500fa4637e1b092c6c1352f89bded3943948f98e99be847abbc43de3f3afb3d1` | `652f9f41b1474b697bf781e279912d9cca3786e7fc77d053043d87811d4eb268` |
| History SHA-256, old = new | `2cac24ebcb1c89cadc737aeb9f7a556d693a86920d93364724dc2f9bc026405a` | `bb1f7bd7cb35e9a7e148135f7f4c531623ebab78dc4c33b14eae01d906700a1e` |

New code digest: `4c7d54a69e4384c0230f42981ae1ddf362c3d4714ed76d7d9f65f04a9e45fe96`.
Unchanged runtime digest: `412fad0a43068e089f1a758b3ee8d0ad8c754c8fcad40649b639b3e88e6b8193`.
Unchanged fixture digest: `eb533a76bf7da05382b3654599edfc95fb403847538abfb2e15316114b689301`.
Unchanged split digest: `9441e7deaa67c80ca5e638b3873e3c4ce75ddb69aec69c0343437a12f5240f06`.
Unchanged preprocessing digest: `c92c53de81d5c6cb748588aaffec91632fbc906d8edbbf2fd15dc9573572e418`.
New numeric checkpoint/provenance bytes are retained in [frozen/](frozen/).
The exact 99-distribution dependency lock is unchanged at
[dependencies.lock.txt](../dependencies.lock.txt).

## New artifact and installed proof

Distinct unpublished identity: `0.6.0a24.post0.dev5+iqt.d148.ml.tty.v2`.
Built wheel and sdist from `git archive` of the exact correction commit with the
existing pinned build environment. The existing canonical sdist normalizer was
used. No old artifact was rebuilt, overwritten or relabeled.

- Wheel: `qcoder-0.6.0a24.post0.dev5+iqt.d148.ml.tty.v2-py3-none-any.whl`.
  SHA-256: `75f974fe94cb4ee7714d965beaa36ff49d01653b8e66b52821d4eff7d608a967`.
- Canonical sdist: `qcoder-0.6.0a24.post0.dev5+iqt.d148.ml.tty.v2.tar.gz`.
  SHA-256: `d80b48ca480988166fd6dee5dc6b388a4aa24a4dd6038366af6cf921107526d3`.
- 156 exact payload files; full wheel inventory 163 members; sdist 169 files.
- RECORD, exact source/wheel/sdist inventory, source↔archive↔installed bytes: PASS.
- New environment: `/tmp/d148-installed-proof-v2/venv`.
  Fresh offline install from the unchanged exact lock and new wheel, no install over
  dev4. Production imports resolve from its own site-packages.
- `pip check`, development-version verifier and `git diff --check`: PASS.
- [artifact-proof.json](artifact-proof.json) and
  [package-verification.json](package-verification.json) retain all inventories,
  hashes and installed origins. New artifacts are also retained in
  `artifacts/d148/packages-v2/`.

## New local MLflow and inert plan

Fresh dedicated local SQLite destination under `artifacts/d148/canonical-v2`.
No remote tracker/artifact store or listener. Experiment ID: `1`;
destination identity digest: `b4bcbecf62bfcc7514c596a8a77deb6bc149db91899edd23e3d5f3328d3891e2`.
Exact source records are new; old records were not mutated or reused.

- Candidate source run: `00c056af168c4309871beaed190fd93d`.
- Baseline source run: `1c78b9fe3855479db40a3207d78201a2`.
- Reserved assessment run: `0c0216d8fb3743ef876f4bad529f5202` (pending, no assessment result).
- Job: `dffa1df4f8054ddebf6ac0630c5cbc04`.
- Attempt: `779f57e6e7184578ad82b3332e4ed9c8`.
- Plan digest: `3cc1c174cd8803b4fbf9354de94935ebf919ea0dbf9e67c5380a83bc173faf43`.
- Challenge: `5ac1b352e57b4bb5b44409b00b072d6d`.

The installed `prepare` command selected those exact two run IDs explicitly.
Installed currentness was revalidated after preparation. See
[pending-plan-summary.json](pending-plan-summary.json).

## Canonical accounting and next human action

Research jobs **0**; candidate model invocations **0**; baseline model invocations
**0**; QNode invocations **0**; held-out examples processed **0**.
**No approval, no scientific entry, no receipt, no result.** Both old and new
canonical workspaces satisfy these absences. No canonical performance was inspected
or evaluated; no D-148 scientific conclusion has been generated.
Self-digesting proof: [zero-science-proof.json](zero-science-proof.json).

Rob must personally run the **new** command in a foreground local terminal:

```bash
/tmp/d148-installed-proof-v2/venv/bin/python -I -B -m qcoder.ml_research --workspace /home/rob/projects/qcoder-iqt-2026-ml-successor-v1/artifacts/d148/canonical-v2 approve
```

Review the displayed plan and personally enter its exact `APPROVE <digest> <challenge>`
line. The command takes no digest or response argument and records approval only.
This worker has not invoked approval for the new canonical plan and will not run
canonical science in this correction turn. Do not use the superseded dev4 command.
Rob-origin approval remains required by the frozen P0 authority invariant.
No extra-layer refinement or Carbon/Phase E work was performed.

## All changed paths in this correction (relative to starting HEAD)

- `development-version.json`
- `evidence/d148/attempts.json`
- `evidence/d148/recut-v2/RETURN.md`
- `evidence/d148/recut-v2/artifact-proof.json`
- `evidence/d148/recut-v2/deterministic-comparison.json`
- `evidence/d148/recut-v2/frozen/baseline-checkpoint.json`
- `evidence/d148/recut-v2/frozen/baseline-training-entered.json`
- `evidence/d148/recut-v2/frozen/candidate-checkpoint.json`
- `evidence/d148/recut-v2/frozen/candidate-training-entered.json`
- `evidence/d148/recut-v2/installed-tests.txt`
- `evidence/d148/recut-v2/package-verification.json`
- `evidence/d148/recut-v2/pending-plan-summary.json`
- `evidence/d148/recut-v2/preservation-proof.json`
- `evidence/d148/recut-v2/real-approval-failure.json`
- `evidence/d148/recut-v2/source-tests.txt`
- `evidence/d148/recut-v2/tty-regression-source.json`
- `evidence/d148/recut-v2/zero-science-proof.json`
- `pyproject.toml`
- `scripts/verify-development-version.py`
- `src/qcoder/__init__.py`
- `src/qcoder/ml_research/job.py`
- `tests/ml_research/test_d148.py`
- `tests/ml_research/test_package.py`
- `tests/test_release_version_consistency.py`
