# Evidence Review walkthrough

This synthetic walkthrough shows how the existing Context Bridge operations form one bounded Explorer Evidence Review capability. It does not add a tool or create a persisted summary artifact.

## 1. Establish current context

Supply a current goal, compact evidence, assumptions, and unresolved questions to `create_context_session_card`.

```text
Current goal: Review whether a synthetic two-qubit circuit is structured for correlated measurements.
Evidence supplied: The user states that the circuit applies a superposition operation, a controlled operation, and two measurements.
Assumption: The external measurement mapping is configured as intended.
Unresolved: Whether an external result will show the intended pattern.
```

The circuit description and configuration statement are **User-provided**. qCoder does not inspect a repository or retrieve prior project context.

## 2. Review readiness

Call `create_run_readiness_card` with the same bounded current evidence. The card separates evidence supplied, observations, inferences, assumptions, what the evidence supports about readiness, what remains unproven, and suggested next checks.

Readiness does not certify correctness, execution validity, runtime, fidelity, backend suitability, or quantum advantage.

## 3. Run elsewhere

Execution is outside qCoder. Keep a compact record:

```text
Run goal: Check for a correlated measurement pattern.
Run environment: Synthetic external simulator description supplied by the user.
Configuration assumption: Measurement ordering matches the intended mapping.
Compact result observation: Outcomes 00 and 11 were dominant in the supplied summary.
Not independently verified: qCoder did not execute the circuit or verify the environment.
```

This external-run record is **User-provided**, not qCoder execution evidence.

## 4. Review the result

Call `create_result_review_context_card` with the compact result record. A bounded response may distinguish:

- **Observed**: information directly present in the explicitly supplied evidence;
- **User-provided**: the external-run and result statements;
- **Inferred**: the reported pattern appears consistent with the intended correlation, based only on the supplied summary;
- **Assumed**: measurement ordering and external configuration;
- **Not proven**: correctness, independent execution validity, detailed outcome behavior, runtime, fidelity, backend suitability, and quantum advantage;
- **Suggested next check**: a user-controlled request for more bounded evidence.

## 5. Compare two explicit points

Call `create_single_loop_evidence_diff` with an explicit before card and after card from this same workflow. The output describes evidence added, what changed, what appears supported, assumptions, unproven statements, and suggested checks.

The comparison performs no lookup. It is not stored history, automatic retrieval, multi-run analysis, regression tracking, or causal diagnosis.

## 6. Decide what to check next

Call `create_next_check_plan` with safe current-request candidates such as:

1. Confirm measurement-bit ordering.
2. Review normalized outcome proportions.
3. Check whether non-correlated outcomes materially affect interpretation.
4. Confirm that the compact summary corresponds to the intended run.

Each recommendation is labeled **Suggested next check**, tied to evidence or uncertainty, ordered, and user-controlled. qCoder does not execute it.

## 7. Prepare an assistant handoff

Call `create_prompt_context` with `review`, `troubleshoot`, or `plan_next_checks`. The mode changes the framing while preserving the evidence, labels, assumptions, and boundaries. It does not scan files, edit code, or perform autonomous work.

## 8. Continue in a supported coding client

Context Bridge carries the bounded Prompt Context into configured Cursor, Claude Code, or Codex clients. Continue only from current-session supplied evidence.

## 9. Use ChatGPT manually

For ChatGPT, copy the share-safe Prompt Context manually. ChatGPT is not a connected Context Bridge integration. Do not include tokens, raw artifacts, local paths, or private project data.

## Boundaries

The walkthrough is synthetic. It uses no customer evidence, account identity, token, backend execution, repository scan, project edit, stored history, hidden retrieval, numerical confidence score, correctness certification, runtime or fidelity prediction, backend ranking, or quantum-advantage claim.
