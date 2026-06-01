# Single-run artifact-to-action (BYO LLM prompt)

Copy-paste into **your** LLM or coding assistant after you have generated `preflight.context.*` and `execution.review.*` with qCoder. Kept in sync with the [qcoder.ai prompt playbook — Single-run artifact-to-action prompt](https://qcoder.ai/manual/llm/prompt-playbook#single-run-artifact-to-action-prompt).

## Copy-paste prompt

```text
I am attaching qCoder preflight and execution review artifacts from one circuit and one run I executed outside qCoder.

Use the JSON files as the structured source of truth. Use the Markdown files as readable context.
Do not assume qCoder executed the circuit or generated my counts; I ran the circuit elsewhere and supplied counts for review.
Do not treat this as a QPU quality score.
Do not rank backends or claim one backend is universally best.
Do not claim fidelity proof, hardware correctness proof, runtime guarantees, or causal savings.
Do not claim optimal shots or optimal bond dimension; qCoder guidance is heuristic only.
Do not treat guidance as optimality proof.
If `guidance_metadata` or `shadow_guidance` appears under `guidance`, read it for transparency (pack id, hash, caveats, optional suggestions) but do not treat shadow output as applied: `shadow_guidance.applied` is false and deterministic MPS `pressure` / `starting_points` remain authoritative in this product slice.
Treat motif or algorithm labels as hypotheses unless they are explicit in the artifact or source.
Do not invent backend-specific settings unsupported by the framework or API I name.

Please respond with:
- a short summary of what the preflight context implies for planning (structure, profiles, guidance) grounded only in those files
- a short summary of what the execution review shows about the counts I provided (metrics, checks, warnings)
- two or three concrete next actions I can take locally (for example adjust shots using the guidance ladder, address a specific warning by name, or inspect a circuit-structure question), each referencing the relevant JSON paths or check names
- what is uncertain and what additional information from me would change your suggestions
- explicit reminders of what would require my own validation or backend-specific knowledge outside qCoder
```
