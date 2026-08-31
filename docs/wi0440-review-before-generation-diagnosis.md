# WI-0440 review-before-generation diagnosis

This is a sanitized source-level diagnosis of the exact public qCoder `0.6.0a24` behavior. It is
not an end-to-end client timing allocation and does not contain client output.

The exact D-119 request has UTF-8 SHA-256
`36e3eee7860487a79680577ee20328d0112b43ffcdd7363c4667dd7cba265e33`. Public a24 classifies it as
`selected_artifact_review`, with `missing_required_selection` and the specific clarification
“Which exact files should qCoder review?” The affirmative-review branch in
`current_loop_request_semantics.py` precedes source generation and cannot represent what is being
reviewed or the requested temporal order. D-079 converts the missing selection into the
`selected_artifact_required` recovery route. The binding then invokes exact-message activation,
which rejects the non-`active_build` route as `activation_exact_message_mode_ineligible`; the
customer receives only the generic bounded failure summary.

The existing Algorithm Blueprint projector is separately reachable and accepts assistant-attributed
values, but it exposes both confirmation actions even when only one goal-restatement group exists.
It therefore cannot by itself make the failed binding route substantive or convergent.

Representative wording splits among selected-file review, direct source generation,
`bounded_single_capability`, and available/inactive behavior. Removing the review clause produces
direct source generation but loses the requested confirmation gate.

The surviving historical observation is 188.8 seconds customer-visible elapsed time. Historical
connected-assistant/model dwell, qCoder-local time, protected-service time, retries, and rendering
time are all `not_observed`; no allocation is inferred. A 2,000-iteration public-a24 local
source-level reproduction measured these median/p95/max times on the campaign host:

- request classification: 0.364 / 0.464 / 0.814 ms;
- route selection: 0.400 / 0.507 / 2.049 ms;
- generic first-value projection: 0.013 / 0.017 / 0.109 ms; and
- serialization: 0.016 / 0.023 / 0.093 ms.

The selected correction is `WI0440_MECHANICAL_PUBLIC_DELIVERY`: carry the connected assistant's
separately attributed semantic axes and concrete recommendations through the existing private
`begin_current_loop` operation, then deterministically validate, revision-bind, retain only in the
active Current Loop, and project the complete three-group review. No protected-service call or
qCoder-authored substantive recommendation is required.
