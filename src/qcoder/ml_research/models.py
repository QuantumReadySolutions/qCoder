"""Fixed native architectures, safe numeric reconstruction, frozen recipes."""
import random

from .contracts import checked, numeric, require, seal

RECIPES = {
    "candidate": {"optimizer": "Adam", "learning_rate": 0.03, "epochs": 80, "batch_size": 120, "seed": 161803, "shuffle": False, "dtype": "float64", "checkpoint_selection": "minimum_validation_bce", "tie_break": "earliest_epoch", "threshold_logit": 0.0},
    "baseline": {"optimizer": "Adam", "learning_rate": 0.03, "epochs": 80, "batch_size": 120, "seed": 141421, "shuffle": False, "dtype": "float64", "checkpoint_selection": "minimum_validation_bce", "tie_break": "earliest_epoch", "threshold_logit": 0.0},
}
ARCHITECTURES = {
    "candidate": {"framework": "PennyLane/PyTorch", "device": "default.qubit", "wires": 2, "embedding": "AngleEmbedding", "rotation": "X", "layers": "StronglyEntanglingLayers", "layer_count": 2, "ranges": [1, 1], "measurements": ["expval(PauliZ(0))", "expval(PauliZ(1))"], "head": "Linear(2,1)", "shots": None, "diff_method": "backprop", "qasm_conversion": False},
    "baseline": {"framework": "PyTorch", "architecture": "Linear(2,4)/ReLU/Linear(4,1)"},
}
SHAPES = {"candidate": {"weights": [2, 2, 3], "head.weight": [1, 2], "head.bias": [1]}, "baseline": {"0.weight": [4, 2], "0.bias": [4], "2.weight": [1, 4], "2.bias": [1]}}


def determinism(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def build(role):
    import torch
    require(role in RECIPES, "model_role")
    determinism(RECIPES[role]["seed"])
    if role == "baseline":
        return torch.nn.Sequential(torch.nn.Linear(2, 4), torch.nn.ReLU(), torch.nn.Linear(4, 1)).double()
    import pennylane as qml

    class Candidate(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weights = torch.nn.Parameter(torch.randn(2, 2, 3, dtype=torch.float64) * 0.1)
            self.head = torch.nn.Linear(2, 1).double()
            self.device = qml.device("default.qubit", wires=2, shots=None, seed=161803)
            self.qnode_invocations = 0

            @qml.qnode(self.device, interface="torch", diff_method="backprop")
            def circuit(features, weights):
                qml.AngleEmbedding(features, wires=[0, 1], rotation="X")
                qml.StronglyEntanglingLayers(weights, wires=[0, 1], ranges=[1, 1])
                return qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliZ(1))
            self.circuit = circuit

        def forward(self, x):
            self.qnode_invocations += 1
            values = torch.stack(self.circuit(x, self.weights), dim=-1)
            return self.head(values)
    return Candidate()


def checkpoint(role, model, fixture, history, epoch):
    from .runtime import code_identity, runtime
    return seal({"schema": "d148.checkpoint.v1", "role": role, "training_code": code_identity(), "training_runtime": runtime(), "architecture": ARCHITECTURES[role], "recipe": RECIPES[role], "fixture_digest": fixture["digest"], "split_digest": fixture["split_digest"], "preprocessing_digest": fixture["preprocessing"]["digest"], "epoch": epoch, "selection_history": history, "selection_partitions": ["train", "validation"], "heldout_evaluations_before_freeze": 0, "state": {key: value.detach().tolist() for key, value in model.state_dict().items()}})


def validate_checkpoint(record, role, fixture):
    checked(record, "d148.checkpoint.v1", ["role", "training_code", "training_runtime", "architecture", "recipe", "fixture_digest", "split_digest", "preprocessing_digest", "epoch", "selection_history", "selection_partitions", "heldout_evaluations_before_freeze", "state"])
    from .runtime import code_identity, runtime
    require(record["training_code"] == code_identity() and record["training_runtime"] == runtime(), "checkpoint_code_runtime")
    require(record["role"] == role and record["architecture"] == ARCHITECTURES[role] and record["recipe"] == RECIPES[role], "checkpoint_architecture_recipe")
    require(record["fixture_digest"] == fixture["digest"] and record["split_digest"] == fixture["split_digest"] and record["preprocessing_digest"] == fixture["preprocessing"]["digest"], "checkpoint_fixture")
    require(record["selection_partitions"] == ["train", "validation"] and type(record["heldout_evaluations_before_freeze"]) is int and record["heldout_evaluations_before_freeze"] == 0, "heldout_selection")
    history = record["selection_history"]
    require(isinstance(history, list) and len(history) == RECIPES[role]["epochs"], "selection_history")
    for epoch, item in enumerate(history, 1):
        require(set(item) == {"epoch", "train_bce", "validation_bce"} and type(item["epoch"]) is int and item["epoch"] == epoch, "selection_epoch")
        numeric(item["train_bce"], []); numeric(item["validation_bce"], [])
        require(item["train_bce"] >= 0 and item["validation_bce"] >= 0, "negative_loss")
    best = min(history, key=lambda item: (item["validation_bce"], item["epoch"]))
    require(type(record["epoch"]) is int and record["epoch"] == best["epoch"], "checkpoint_selection")
    require(set(record["state"]) == set(SHAPES[role]), "checkpoint_keys")
    for key, shape in SHAPES[role].items():
        numeric(record["state"][key], shape)
    return record


def reconstruct(record, role, fixture):
    import torch
    validate_checkpoint(record, role, fixture)
    model = build(role)
    model.load_state_dict({key: torch.tensor(value, dtype=torch.float64) for key, value in record["state"].items()}, strict=True)
    return model.eval()
