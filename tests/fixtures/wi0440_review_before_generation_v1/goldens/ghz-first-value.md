## Goal and scope

- **Recommended interpretation:** Create a concrete three-qubit Qiskit GHZ preparation and measurement program only after the customer confirms the displayed plan.
- **Limitation 1:** The example is not presented as proof of entanglement.
- **Limitation 2:** The review does not claim algorithm correctness.
- **Limitation 3:** The review makes no hardware-performance claim.

## Implementation

- **Implementation recommendation 1:** Use Qiskit QuantumCircuit.
- **Implementation recommendation 2:** Three qubits prepared with one H and a two-CX entangling chain
- **Implementation recommendation 3:** QuantumCircuit with H on q0, CX from q0 to q1, CX from q1 to q2, and measurements
- **Implementation recommendation 4:** Measure q0 to c0, q1 to c1, and q2 to c2
- **Implementation recommendation 5:** Direct readable Python with explicit quantum and classical registers
- **Dependency version:** No dependency version was selected silently.
- **Execution environment:** No execution environment was selected silently.

## Output and authority

- **Output artifact:** A readable three-qubit GHZ source example in Python
- **Source delivery:** Inline after confirmation.
- **Generation authority:** Python source will be produced after you confirm these choices.
- **Execution authority:** Execution was not requested and is not authorized.
- **Authority separation:** Confirming these choices does not authorize execution.
- **Deferred execution choices:** Backend, shots, seed, and result handling remain deferred.

- Use recommended choices
- Review or change choices
