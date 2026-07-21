from qiskit import QuantumCircuit as Circuit


def amplify_selected_state(circuit, rounds):
    for _ in range(rounds):
        circuit.h([0, 1])
        circuit.x([0, 1])
        circuit.cz(0, 1)
        circuit.x([0, 1])
        circuit.h([0, 1])


def assemble_search(rounds):
    circuit = Circuit(2)
    circuit.h([0, 1])
    amplify_selected_state(circuit, rounds)
    circuit.measure_all()
    return circuit
