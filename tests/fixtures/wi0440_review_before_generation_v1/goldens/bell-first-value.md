## Goal and scope

- **Recommended interpretation:** Create a minimal two-qubit Qiskit program that prepares \|Φ+\> = (\|00\> + \|11\>)/sqrt(2), measures both qubits in the computational basis, and produces readable Python only after the customer confirms the plan.
- **Customer constraint 1:** Qiskit program
- **Customer constraint 2:** prepares and measures a Φ+ Bell state
- **Customer constraint 3:** Before generating the code
- **Limitation 1:** The example is not presented as proof of entanglement.
- **Limitation 2:** The review does not claim algorithm correctness.
- **Limitation 3:** The review makes no hardware-performance claim.

## Implementation

- **Implementation recommendation 1:** Use Qiskit QuantumCircuit.
- **Implementation recommendation 2:** Use two qubits and two classical bits.
- **Implementation recommendation 3:** Apply H to q0.
- **Implementation recommendation 4:** Apply CX from q0 to q1.
- **Implementation recommendation 5:** Measure q0 to c0 and q1 to c1.
- **Implementation recommendation 6:** Produce direct readable Python.
- **Material choice: Framework:** Qiskit
- **Material choice: Construction:** QuantumCircuit with H on q0 followed by CX from q0 to q1
- **Material choice: Representation:** Direct readable Python
- **Dependency version:** No dependency version was selected silently.
- **Execution environment:** No execution environment was selected silently.

## Output and authority

- **Output artifact:** Readable Python source after confirmation
- **Generation authority:** Python source will be produced after you confirm these choices.
- **Execution authority:** Execution was not requested and is not authorized.
- **Authority separation:** Confirming these choices does not authorize execution.
- **Deferred execution choices:** Backend, shots, seed, and result handling remain deferred.

- Use recommended choices
- Review or change choices
