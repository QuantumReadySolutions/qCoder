from qiskit import QuantumCircuit as Circuit
from qiskit.circuit import ParameterVector as Angles


def assemble_layers(width, depth):
    beta = Angles("beta", depth)
    gamma = Angles("gamma", depth)
    circuit = Circuit(width)
    for layer in range(depth):
        circuit.rzz(gamma[layer], 0, 1)
        for qubit in range(width):
            circuit.rx(2 * beta[layer], qubit)
    circuit.measure_all()
    return circuit
