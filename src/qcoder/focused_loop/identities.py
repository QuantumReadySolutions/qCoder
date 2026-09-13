"""Frozen schema, regime, fixture, and generator identities for the first focused loop.

Every identity here is fixed by the controlling Roadmap product specification
``QCODER-EXPLORER-FIRST-FOCUSED-LOOP-VERTICAL-PRODUCT-SPECIFICATION-V1``. Nothing in
this module may be widened to a second regime, method, or fixture family without a
new product record.
"""

from __future__ import annotations

REGIME_ID = "local_aer_stabilizer_clifford_memory_binding_v1"

OBJECTIVE_SCHEMA_ID = "qcoder.evidence_objective.v1"
EXECUTION_PROFILE_SCHEMA_ID = "qcoder.execution_profile.v1"
RESOURCE_RECEIPT_SCHEMA_ID = "qcoder.resource_receipt.v1"
CHI_REQUIRED_CLAIM_SCHEMA_ID = "qcoder.chi_required_claim.v1"
METHOD_APPLICABILITY_SCHEMA_ID = "qcoder.method_applicability.v1"
CANDIDATE_RECOMMENDATION_SCHEMA_ID = "qcoder.candidate_recommendation.v1"
RESULT_PROTOCOL_SCHEMA_ID = "qcoder.result_protocol.stabilizer_predicate_satisfaction.v1"
EXECUTION_PLAN_SCHEMA_ID = "qcoder.execution_plan.v1"
EXECUTION_AUTHORITY_SCHEMA_ID = "qcoder.execution_authority.v1"
EXECUTION_RECEIPT_SCHEMA_ID = "qcoder.execution_receipt.v1"
ANALYSIS_RESULT_SCHEMA_ID = "qcoder.analysis_result.v1"
NEXT_ACTION_SCHEMA_ID = "qcoder.next_action.v1"

FIXTURE_MANIFEST_SCHEMA_ID = "qcoder.focused_loop.fixture_manifest.v1"
ANSWER_KEY_SCHEMA_ID = "qcoder.focused_loop.answer_key.v1"

#: The accepted strict result manifest this package composes with but never edits.
STRICT_RESULT_MANIFEST_SCHEMA_ID = "qcoder.current_loop.strict_result_manifest.v3"
STRICT_RESULT_MANIFEST_MAX_OUTCOMES = 1_024

GENERATOR_ID = "qcoder.focused_loop.nested_bell_generator"
GENERATOR_VERSION = "1"

PRIMARY_FIXTURE_ID = "FX-CLIF-ACCEPT-01"
PRIMARY_FIXTURE_NAME = "NESTED_BELL_64Q_SMALL_SUPPORT_PREDICATE_V1"
HELDOUT_FIXTURE_ID = "FX-CLIF-HOLDOUT-02"

CHI_DERIVATION_ID = "qcoder.focused_loop.nested_bell_natural_order_central_cut"
CHI_DERIVATION_VERSION = "1"
MPS_FLOOR_PROCEDURE_ID = "mps_dense_complex128_coefficient_floor_v1"

EXACTNESS_POLICY_EXACT_REQUIRED = "exact_required"
METHOD_MPS_EXACT = "mps_exact"
METHOD_MPS_APPROXIMATE = "mps_approximate"
METHOD_STABILIZER = "stabilizer"

FIXED_SHOTS = 598
CONFIDENCE_LEVEL = 0.95
TARGET_LOWER_BOUND = 0.995

#: Limitation that must travel with every ``chi_required`` claim in this family.
AER_MPS_LIMITATION = "aer_internal_mps_qubit_reordering_not_characterized"

#: Exclusions that must travel with every coefficient-floor lower bound.
MPS_FLOOR_EXCLUSIONS = (
    "aer_python_overhead",
    "allocator_effects",
    "metadata",
    "result_materialization",
    "temporary_decomposition_svd_workspace",
)
