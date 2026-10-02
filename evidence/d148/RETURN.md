# Tactical_Conference_1 — D-148 A–D approval-boundary return

Status: **implementation, frozen preparation and installed synthetic proof complete;
canonical scientific proof pending Rob-origin approval**. This is not completed A–D
scientific acceptance, conference approval, publication, or Phase E authorization.

Campaign: `QCODER_IQT_2026_ML_RESEARCH_SUCCESSOR_IMPLEMENTATION_AND_PROOF_V1`.
Family: `FX-QML-ACCEPT-01 / PENNYLANE_TWO_MOONS_2Q_HYBRID_CLASSIFIER_V1`.

## Exact Git lineage and isolation

- Branch: `conference/iqt-2026-ml-research-successor-v1`.
- Verified clean starting HEAD/base: `6eb17cbc68752cf0ed4d29b0d67e4544d6efd8f8`.
- Starting tree: `3430bade826d7d969a4bb93076ee351ff438a5d2`.
- Base parent: `ff6e052e95a31073a0142ff99741f91eb62e6668`.
- Committed/pushed implementation and exact artifact source:
  `c2d0132cba6c0fe896f5d6bd28746c2946712ae3`.
- Artifact source tree: `8cbad3ac82c9d328a59388221a1c0bee46311719`.
- Artifact-source parent is the exact starting HEAD above. The final handoff message
  supplies the evidence commit's HEAD/tree/parent (a report cannot embed its own Git hash).
- Work stayed in the assigned worktree, with dedicated temporary build/install proof
  outside source as required. No other qCoder/qcoder-internal worktree was opened for
  implementation or modified. No protected Stage-D production source changed.
- WI-0441/Tactical_38 branch/state, provider operations, credentials, owner, existing
  locks/quotas/counters and review processes were untouched. The inherited **public
  packaging test file named `test_wi0441_public_build_allowlist_v1.py`** has only its
  expected public inventory count updated from 147 to 156 for the explicitly requested
  nine package additions; this does not alter WI-0441 implementation or branch/state.
- No D-147 file was edited, rebuilt, overwritten, installed over, or repurposed.
  Its actual hash recheck remains **not established**: the file path was requested and
  has not been supplied. Required expected SHA-256 is
  `73f9c7d0f8e396338a62cfb964df0244a179c5cf4352d5773f0da95b0ac5138c`.

## Runtime and dependencies

Python 3.12.9, cpython, x86_64;
`Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.35`. CPU only, float64, one PyTorch thread,
deterministic algorithms. Runtime digest: `412fad0a43068e089f1a758b3ee8d0ad8c754c8fcad40649b639b3e88e6b8193`.

Exact primary pins: PennyLane 0.44.0; PyTorch 2.6.0+cpu; MLflow 3.1.4;
NumPy 2.2.6; SciPy 1.15.3; scikit-learn 1.6.1; SQLAlchemy 2.0.40;
pennylane-lightning 0.44.0; gast 0.6.0; astunparse 1.6.3;
pytest 8.3.5; build 1.2.2.post1; setuptools 80.9.0; wheel 0.45.1.
All 99 installed distributions, including transitive pins, are retained in
[dependencies.lock.txt](dependencies.lock.txt). Both environments pass `pip check`.
Heavy ML imports remain optional/lazy; ordinary `import qcoder` loads none of them.

## Scientific freeze

Two moons: 200 examples, two numeric features, binary labels, noise 0.15,
generator seed 314159. Stratified split seed 271828, 120/40/40. Standardization
means/scales are fit on training data only, population standard deviation (ddof=0).
Exact bytes are retained in [frozen/](frozen/) and raw byte SHA-256 values in
[freeze-proof.json](freeze-proof.json); regeneration is not the acceptance authority.

- Fixture digest: `eb533a76bf7da05382b3654599edfc95fb403847538abfb2e15316114b689301`.
- Data digest: `2606f25d52bb7370b9b371ffde6fd4e732ae0cca88b5a5966aab0376c32dd7ef`.
- Label digest: `42d8d1eba20143f583791be0ea07c1f186b7e632ddefb9e9b7badca7e7e2fa1e`.
- Split digest: `9441e7deaa67c80ca5e638b3873e3c4ce75ddb69aec69c0343437a12f5240f06`.
- Train partition: `5fcd2e04c0a9c10250b85fbfde1e021055c48bc0912a7ad4f831b2a5f48bdb73`.
- Validation partition: `dfbc073b4a9aa645d03d553f1879ab726543fd81632ceae4a55640a72a35d0a0`.
- Test partition: `56db23de81933e00a72d84b8d2e8e54756959b8a0c54d30da1e4b9d2094d5be0`.
- Preprocessing digest: `c92c53de81d5c6cb748588aaffec91632fbc906d8edbbf2fd15dc9573572e418`.

Candidate: native PennyLane/PyTorch default.qubit, two wires, AngleEmbedding
(X rotations), two StronglyEntanglingLayers (ranges [1,1]), Z expectation per
wire and Linear(2,1) head. Analytic shots=None, backprop; no QASM conversion.
Baseline: PyTorch Linear(2,4), ReLU, Linear(4,1).

Both recipes: Adam, learning rate 0.03, 80 epochs, full batch 120, no shuffle,
float64, fixed logit threshold >=0 predicts one; minimum validation BCE selects
checkpoint, earliest epoch breaks exact ties. All Python/NumPy/PyTorch seeds:
candidate 161803, baseline 141421; analytic candidate device seed 161803.
Neither recipe nor seed was changed in response to held-out data.

- Candidate selected epoch: 80;
  validation BCE 0.28894970554781835.
  Checkpoint digest: `3c681713c68f3dd8837db7506a4faef9c83de61ed8f656210b4a24a69d84f472`.
- Baseline selected epoch: 80;
  validation BCE 0.21865491103578596.
  Checkpoint digest: `6ea15ff9a817aef3dffce853e0cb901360326804584811d071060a88683ed8d9`.
- All 80 epoch train/validation losses per role are in the numeric checkpoint JSON.
  Each checkpoint binds the architecture, recipe, fixture/split/preprocessing,
  code, runtime, exact numeric parameters and selected epoch. No pickle/model
  import or tracker-supplied source is accepted.
- Code digest: `89f7a7a767763d89ad3d2c630b15814d3b3a2cdfc5eda4c66d2b2f7fdb17cc0d`.

Held-out was unused for selection: training APIs read only train and validation;
a real training test succeeds after deleting test.json; both canonical preparation
entry records list those two partitions; sealed checkpoints report zero held-out
selection evaluations; the canonical workspace has no entry/approval/result/receipt.
Reading fixture bytes for hashing, splitting and stratification is distinct from
running a model or selecting a recipe using held-out performance.

## Canonical job and user authority

- Plan digest: `fcd115f49d3726c3a782725a4872a63e886295153a11a5c168d21f11ef25c9fc`.
- Job: `3445e7e975ac4c3ca8d3c9ac9a16084a`.
- Attempt: `7fb4324afecb403881d8b31a4e1c6b25`.
- Challenge: `a03f7b2af9654372bea1d3fd8738c415`.
- Protocol: `d148.result.v1`, accuracy on exactly 40, threshold zero, shots null.
- Budget: one research job, 60 seconds, 40 invocations per model, 40 QNode calls.
- Approval/receipt/result/reuse identities: **not yet established**.
- Canonical research attempts/model invocations/QNode invocations/held-out examples:
  **0 / 0 candidate / 0 baseline / 0 / 0**. No canonical device evaluation occurred.
- First candidate and baseline held-out metrics, descriptive delta, deterministic
  conclusion and next action: **not established; must not be inferred from validation**.

The inert plan was prepared using the installed artifact and exact explicit run IDs.
Currentness was checked again through that installed artifact. Mutation of plan,
checkpoint, split or runtime invalidates authority/currentness. Entry is fsynced
before evaluation; any entered, failed, interrupted, timed-out or unknown attempt
cannot automatically retry. Exact completed work reuses its verified result with no
new model evaluation. Plan/run APIs cannot mint user approval from a supplied digest.

Rob must personally run this in a local interactive terminal:

```bash
/tmp/d148-installed-proof/venv/bin/python -I -m qcoder.ml_research --workspace /home/rob/projects/qcoder-iqt-2026-ml-successor-v1/artifacts/d148/canonical-v1 approve
```

Review the displayed plan and personally enter the exact `APPROVE <digest> <challenge>`
line the program displays. Do not ask the assistant to operate the TTY or create an
approval file. This command records approval only; canonical `run` remains a later
step. No approval command or challenge response has been executed by this worker.
The ceremony relies on trusted local OS/TTY ownership; it is not authentication
against malicious same-UID filesystem or terminal control.

## MLflow and delivery proof

Dedicated local SQLite store, local file artifacts, no server/listener, remote store,
registry deployment, project-history scan or best-run search. Experiment ID
`1`; exact destination identity digest
`ae320dcdc5abd62294bab713e624515b496f62580eb0c3329e80df85b30d5ac6`. Database contents remain untracked local artifacts.

- Candidate training run: `5a8fbc24aa6845ceb08d1150ac495683`.
- Baseline training run: `c285ceb957b84ef49e475f37c5931d12`.
- Reserved assessment run: `9f820359e11b478b8fbb0bcc19305c90` (pending; no canonical assessment).
- Canonical output assessment/read-back: **pending accepted canonical completion**.

Real local integration tests established successful write/read-back, tracker failure
with science preserved, delivery-only retry, duplicate delivery, metric mismatch
refusal, free-text instruction inertness, tampered source params, incompatible source
status, and remote artifact rejection. The immutable local result precedes delivery;
reserved output identity prevents duplicate science or identity search. Read-back
validates exact run/source/job/plan/result IDs, metrics, conclusion, action, schema
and artifact self-digest through the real MLflow client and local artifact path.

Provenance explicitly separates qcoder_established, external_reported,
assistant_inference and not_established. The deterministic conclusion/action cannot
be replaced by tracker free text or assistant interpretation.

The source and installed suites each ran one real successful **synthetic sin/cos**
held-out job: 40 candidate, 40 baseline and 40 QNode invocations; PennyLane Tracker
observed 40 executions and 40 simulations. This is not canonical fixture evidence
and is not labeled one circuit dispatch. Failure seams use simulated bounded state;
none constitutes Rob-origin canonical authority. Training preparation is separate
from research-job accounting; training device execution counts were not instrumented
and are not invented.

## Package and clean installed evidence

Unpublished successor `0.6.0a24.post0.dev4+iqt.d148.ml.v1`.
Build used `git archive` of the exact implementation commit and
`.venv/bin/python -m build --no-isolation --wheel --sdist`; the existing canonical
sdist normalizer removed only the validated generated setuptools setup.cfg.

- Wheel SHA-256: `1882df310346b83b65d0ccfaa4c41f1a3b7bf74dda1093ff42753ff553836025`.
- Canonical sdist SHA-256: `42bae6edd589e3315debab985a0182a345a01177b7eaa9d66488f2bd3e7a5af4`.
- Exact package payload: 156 files = inherited 147 + nine explicit ML modules.
- Full wheel inventory: 163 members. Full canonical sdist inventory: 169 files.
- RECORD digests/sizes and inventory: PASS.
- Source↔wheel↔sdist↔installed bytes: PASS for all 156 payload files.
- Fresh isolated environment outside source installed offline from exact lock and
  distinct wheel. Production imports resolve from
  `/tmp/d148-installed-proof/venv/lib/python3.12/site-packages/qcoder/`.
- No new protected/private policy or campaign evidence enters the wheel/sdist.
  The exact allowlist adds only qcoder.ml_research and its nine named .py files.
- Full per-file inventories and hashes: [artifact-proof.json](artifact-proof.json).
  Verifier result: [package-verification.json](package-verification.json).
- Artifacts retained under the worktree's ignored `artifacts/d148/packages/`.
- Canonical installed scientific proof remains pending real approval, not claimed.

## Commands, outcomes and corrections

1. `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/ml_research tests/test_focused_loop_contracts_v1.py tests/test_focused_loop_package_isolation_v1.py tests/test_public_package_metadata.py`
   — **123 passed**, 57.95 seconds.
2. `PYTHONDONTWRITEBYTECODE=1 /tmp/d148-installed-proof/venv/bin/python -I -m pytest -q -c /dev/null /tmp/d148-installed-proof/tests/test_d148.py`
   from `/tmp` — **41 passed**, 55.29 seconds. No repository pytest pythonpath.
3. `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_wi0441_public_build_allowlist_v1.py tests/test_release_version_consistency.py`
   — **43 passed**, 0.22 seconds.
4. `scripts/verify_public_package_allowlist.py --wheel ... --sdist ...`,
   `scripts/prove_d148_artifact.py --source ... --wheel ... --sdist ... --python ... --commit c2d0132cba6c0fe896f5d6bd28746c2946712ae3`,
   `pip check` in both environments, and `git diff --check` — PASS.

Failed/superseded attempts are preserved in [attempts.json](attempts.json): initial
sandbox DNS failure; missing gast import (16 pass/1 fail/18 errors); incompatible
SQLAlchemy 2.1 (17 pass/18 errors); isolation test mistaking model.eval() for Python
eval (37 pass/1 fail); and a wrong relative test-copy path before installed tests.
All were contained and corrected before canonical plan creation. No held-out outcome
was observed and no recipe was tuned in response to any of these corrections.

The full repository suite was not claimed or run. Required focused, package,
version, scientific, authority and installed integration checks are reported above.

## Remaining work after Rob approval

Run exactly one canonical installed job; retain receipt and canonical predictions;
independently recompute candidate/baseline correct/40 and descriptive delta; apply
frozen D-148 conclusion/next-action logic; deliver and read back the canonical
assessment; prove exact canonical reuse without reevaluation; complete the D-147
hash-only recheck once its path is supplied; return final A–D evidence to Tactical.
Do not execute the future extra-layer refinement or start Carbon/natural-client
Phase E. A disappointing canonical result remains a successful truthful product result.

## All changed paths relative to the authorized base

- `MANIFEST.in`
- `development-version.json`
- `docs/d148-implementation-plan.md`
- `evidence/d148/RETURN.md`
- `evidence/d148/artifact-proof.json`
- `evidence/d148/attempts.json`
- `evidence/d148/dependencies.lock.txt`
- `evidence/d148/freeze-proof.json`
- `evidence/d148/frozen/baseline-checkpoint.json`
- `evidence/d148/frozen/baseline-training-entered.json`
- `evidence/d148/frozen/candidate-checkpoint.json`
- `evidence/d148/frozen/candidate-training-entered.json`
- `evidence/d148/frozen/fixture.json`
- `evidence/d148/frozen/recipes.json`
- `evidence/d148/frozen/test.json`
- `evidence/d148/frozen/train.json`
- `evidence/d148/frozen/validation.json`
- `evidence/d148/package-verification.json`
- `evidence/d148/pending-plan-summary.json`
- `evidence/d148/runtime.json`
- `packaging/public-package-allowlist-v1.json`
- `pyproject.toml`
- `scripts/prove_d148_artifact.py`
- `scripts/verify-development-version.py`
- `src/qcoder/__init__.py`
- `src/qcoder/ml_research/__init__.py`
- `src/qcoder/ml_research/__main__.py`
- `src/qcoder/ml_research/contracts.py`
- `src/qcoder/ml_research/fixture.py`
- `src/qcoder/ml_research/job.py`
- `src/qcoder/ml_research/models.py`
- `src/qcoder/ml_research/runtime.py`
- `src/qcoder/ml_research/tracker.py`
- `src/qcoder/ml_research/training.py`
- `tests/ml_research/test_d148.py`
- `tests/ml_research/test_package.py`
- `tests/test_release_version_consistency.py`
- `tests/test_wi0441_public_build_allowlist_v1.py`
