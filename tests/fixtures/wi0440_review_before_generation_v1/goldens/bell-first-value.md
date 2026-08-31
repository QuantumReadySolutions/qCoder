# Review before generation

Create a minimal two-qubit Qiskit program that prepares |Φ+> = (|00> + |11>)/sqrt(2), measures both qubits in the computational basis, and produces readable Python only after the customer confirms the plan.

## Goal and scope

- **Intended artifact:** A minimal Bell-state preparation and measurement example in Python
- **Quantum scope:** Two qubits preparing the Φ+ state
- **Classical scope:** Two matching classical bits
- **Measurement basis:** Computational-basis measurement

## Implementation

- **Framework:** Qiskit
- **Construction:** QuantumCircuit with H on q0 followed by CX from q0 to q1
- **Measurement mapping:** Measure q0 to c0 and q1 to c1
- **Output structure:** Direct readable Python
- **Dependency version:** No dependency version is selected silently
- **Execution environment:** No execution environment is selected silently

## Output and authority

- **Artifact after confirmation:** Python source only after the displayed revision is confirmed
- **Generation authority:** Held for exact confirmation of this displayed revision
- **Execution authority:** Not requested; any execution requires separate authorization

## Deferred choices

- **Backend:** Deferred until execution is separately requested.
- **Shots:** Deferred until execution is separately requested.
- **Seed:** Deferred until execution is separately requested.
- **Result handling:** Deferred until execution is separately requested.

## Limitations and nonclaims

- The example is not presented as proof of entanglement.
- The review does not claim algorithm correctness.
- The review makes no hardware-performance claim.

Revision: `review-revision-813384004d452d2074377eeb78513c841a382ab813725622a0eb9bc6c1a24d1d`

## Actions

- Use recommended choices
- Review or change choices
