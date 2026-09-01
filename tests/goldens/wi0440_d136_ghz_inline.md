## Goal and scope

- **Recommended interpretation:** Create a three-qubit GHZ Qiskit program and review its implementation plan before producing source.
- **Requested framework:** Qiskit
- **Requested artifact:** Source for the requested program.
- **Requested operation:** Prepare and measure the requested quantum state.
- **Limitation 1:** The review does not claim hardware performance.

## Implementation

- **Framework:** Use Qiskit QuantumCircuit.
- **Registers:** Use three qubits and three classical bits.
- **Preparation:** Apply H to q0, then CX from q0 to q1 and CX from q1 to q2.
- **Measurement:** Measure all three qubits into matching classical bits.
- **Dependency version:** No dependency version was selected silently.
- **Execution environment:** No execution environment was selected silently.

## Output and authority

- **Output artifact:** Readable Python source after confirmation
- **Source delivery:** Inline after confirmation.
- **Generation authority:** Python source will be produced after you confirm these choices.
- **Execution authority:** Execution was not requested and is not authorized.
- **Authority separation:** Confirming these choices does not authorize execution.
- **Deferred execution choices:** Backend, shots, seed, and result handling remain deferred.

- Use recommended choices
- Review or change choices
