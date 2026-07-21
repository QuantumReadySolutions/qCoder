from qiskit import QuantumCircuit as Circuit


def assemble_example(width):
    circuit = Circuit(width)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure_all()
    return circuit
