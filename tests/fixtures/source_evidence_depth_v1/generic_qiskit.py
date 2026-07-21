from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Parameter

QUBITS = 1 + 1
SHOTS = 512
PRIVATE_LABEL = "withhold-this-synthetic-label"
SAMPLE_DATA = ["alpha", "beta", "gamma"]


def add_entanglement(circuit):
    circuit.h(0)
    circuit.cx(0, 1)


def build_circuit():
    theta = Parameter("theta")
    circuit = QuantumCircuit(QUBITS, QUBITS)
    add_entanglement(circuit)
    circuit.ry(theta, 0)
    circuit.measure_all()
    transpile(circuit, optimization_level=2, seed_transpiler=11)
    return circuit
