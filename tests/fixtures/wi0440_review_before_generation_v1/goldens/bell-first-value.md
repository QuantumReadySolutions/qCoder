# Review before generation

Create a minimal two-qubit Qiskit program that prepares \|Φ+\> = (\|00\> + \|11\>)/sqrt(2), measures both qubits in the computational basis, and produces readable Python only after the customer confirms the plan.

## Goal and scope

- **Recommended interpretation:** Create a minimal two-qubit Qiskit program that prepares \|Φ+\> = (\|00\> + \|11\>)/sqrt(2), measures both qubits in the computational basis, and produces readable Python only after the customer confirms the plan.
- **Customer constraint:** Qiskit program
- **Customer constraint:** prepares and measures a Φ+ Bell state
- **Customer constraint:** Before generating the code

## Implementation

- **Implementation recommendation 1:** Use Qiskit QuantumCircuit.
- **Implementation recommendation 2:** Use two qubits and two classical bits.
- **Implementation recommendation 3:** Apply H to q0.
- **Implementation recommendation 4:** Apply CX from q0 to q1.
- **Implementation recommendation 5:** Measure q0 to c0 and q1 to c1.
- **Implementation recommendation 6:** Produce direct readable Python.
- **Dependency version:** No dependency version was selected silently.
- **Execution environment:** No execution environment was selected silently.

## Output and authority

- **Output artifact:** Readable Python source after confirmation
- **Generation authority:** Python source is produced only after the stored displayed review is confirmed.
- **Execution authority:** Execution was not requested and is not authorized.
- **Authority separation:** Confirmation of source generation does not authorize execution.
- **Deferred execution choices:** Backend, shots, seed, and result handling remain deferred.

## Deferred choices

- **Deferred choice 1:** Backend remains deferred until execution is separately requested.
- **Deferred choice 2:** Shots remain deferred until execution is separately requested.
- **Deferred choice 3:** Seed remains deferred until execution is separately requested.
- **Deferred choice 4:** Result handling remains deferred until execution is separately requested.

## Limitations and nonclaims

- The example is not presented as proof of entanglement.
- The review does not claim algorithm correctness.
- The review makes no hardware-performance claim.

## Actions

- Use recommended choices
- Review or change choices
