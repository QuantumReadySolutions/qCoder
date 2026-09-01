## Goal and scope

- **Recommended interpretation:** Create a three-qubit GHZ Qiskit program and wait for confirmation before producing source.
- **Limitation 1:** The review does not claim hardware performance.
- **Clarification needed:** Should measurements cover all three qubits?

## Implementation

- **Framework:** Use Qiskit QuantumCircuit.
- **Registers:** Use three qubits and three classical bits.
- **Preparation:** Apply H to q0, then CX from q0 to q1 and q2.
- **Measurement:** Measure all qubits to matching classical bits.
- **Dependency version:** No dependency version was selected silently.
- **Execution environment:** No execution environment was selected silently.

## Output and authority

- **Output artifact:** Readable Python source after confirmation
- **Source delivery:** Inline after confirmation.
- **Generation authority:** Python source will be produced after you confirm these choices.
- **Execution authority:** Execution was not requested and is not authorized.
- **Authority separation:** Confirming these choices does not authorize execution.
- **Deferred execution choices:** Backend, shots, seed, and result handling remain deferred.
