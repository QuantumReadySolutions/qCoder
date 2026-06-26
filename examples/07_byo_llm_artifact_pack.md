# 07: BYO LLM artifact pack (OSS)

**BYO** means *bring your own*: you open your LLM or coding assistant in an environment **you** control and attach qCoder files (or paste excerpts). qCoder **does not** call an LLM, host LLM compute, upload your prompts, or send circuit data to a qCoder inference service.

For the full single-run workflow, see [`06_single_run_intelligence.md`](./06_single_run_intelligence.md).

## Which artifacts to give a user-managed LLM

| File | Role |
| --- | --- |
| `preflight.context.json` | Structured preflight source of truth (structure, optional profiles, optional guidance). |
| `preflight.context.md` | Human-readable preflight summary. |
| `execution.review.json` | Structured review from **counts you supplied** (metrics, checks, warnings). |
| `execution.review.md` | Human-readable review summary. |

## How to use them with an assistant

- Treat **JSON** as the **source of truth** for fields, checks, and warnings.
- Treat **Markdown** as **readable context**; it should match JSON but JSON wins on ambiguity.
- Tell the assistant explicitly: **qCoder did not execute the circuit** and **did not generate your counts**; you ran elsewhere and passed counts into `qcoder review`.

## Security and scope

- Do **not** paste API keys, tokens, internal URLs, or proprietary code you are not allowed to share—only attach what **you** choose.
- qCoder artifacts may include circuit-derived metadata; review your org policy before pasting into a third-party model.

## Copy-paste prompt

Use the text in [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md)—aligned with the [qcoder.ai prompt playbook](https://qcoder.ai/manual/llm/prompt-playbook#single-run-artifact-to-action-prompt).

## Boundary reminder

qCoder produces local deterministic files only. This workflow does not add hosted qCoder compute, qCoder-hosted LLM, or telemetry upload.
