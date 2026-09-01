## Goal and scope

- **Recommended interpretation:** Create a minimal two-qubit Qiskit program that prepares \|Φ+\> = (\|00\> + \|11\>)/sqrt(2), measures both qubits in the computational basis, and produces readable Python only after the customer confirms the plan.
- **Customer constraint 1:** Qiskit program
- **Customer constraint 2:** prepares and measures a Φ+ Bell state
- **Customer constraint 3:** Before generating the code
- **Limitation 1:** The example is not presented as proof of entanglement.
- **Limitation 2:** The review does not claim algorithm correctness.
- **Limitation 3:** The review makes no hardware-performance claim.

## Implementation

- **Framework:** Use Qiskit QuantumCircuit.
- **Registers:** Use two qubits and two classical bits.
- **Preparation:** Apply H to q0, then CX from q0 to q1.
- **Measurement:** Measure q0 to c0 and q1 to c1.
- **Representation:** Produce direct readable Python.
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
