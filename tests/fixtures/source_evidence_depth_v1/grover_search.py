from qiskit import QuantumCircuit

SEARCH_WIDTH = 3
ITERATIONS = 1 + 1
MARKED_STATE = "101"


def phase_oracle(circuit):
    circuit.mcp(3.14159, [0, 1], 2)


def diffusion(circuit):
    circuit.h(range(SEARCH_WIDTH))
    circuit.x(range(SEARCH_WIDTH))
    circuit.mcx([0, 1], 2)
    circuit.x(range(SEARCH_WIDTH))
    circuit.h(range(SEARCH_WIDTH))


def build_search():
    circuit = QuantumCircuit(SEARCH_WIDTH, SEARCH_WIDTH)
    for _ in range(ITERATIONS):
        phase_oracle(circuit)
        diffusion(circuit)
    circuit.measure_all()
    return circuit
