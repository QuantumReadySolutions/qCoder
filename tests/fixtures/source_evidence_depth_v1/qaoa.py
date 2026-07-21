from qiskit import QuantumCircuit
from qiskit.circuit import ParameterVector
from qiskit.primitives import Sampler

LAYERS = 2
SHOTS = 256
PROBLEM_EDGES = [(0, 1), (1, 2)]


def add_cost_layer(circuit, gamma):
    circuit.rzz(gamma, 0, 1)


def add_mixer_layer(circuit, beta):
    circuit.rx(beta, range(3))


def build_qaoa():
    gamma = ParameterVector("gamma", LAYERS)
    beta = ParameterVector("beta", LAYERS)
    circuit = QuantumCircuit(3, 3)
    for layer in range(LAYERS):
        add_cost_layer(circuit, gamma[layer])
        add_mixer_layer(circuit, beta[layer])
    bound = circuit.assign_parameters({gamma[0]: 0.25, beta[0]: 0.5})
    bound.measure_all()
    Sampler().run(bound, shots=SHOTS)
    return bound
