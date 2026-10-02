"""One predeclared training pass per role; held-out partition never opened."""
from pathlib import Path
import copy

from .contracts import read, require, seal, write_new
from .fixture import selection_data, standardized
from .models import ARCHITECTURES, RECIPES, build, checkpoint, validate_checkpoint


def freeze_recipes(root):
    record = seal({"schema": "d148.recipes.v1", "recipes": RECIPES, "architectures": ARCHITECTURES, "heldout_metric": "accuracy@logit>=0", "selection": "validation BCE, earliest epoch tie", "test_use": "only_after_freeze_and_user_approval"})
    write_new(Path(root) / "recipes.json", record)
    return record


def train(root, role):
    import torch
    root = Path(root)
    frozen = read(root / "recipes.json")
    require(frozen["recipes"] == RECIPES and frozen["architectures"] == ARCHITECTURES, "recipe_not_frozen")
    fixture, train_data, validation = selection_data(root)
    recipe = RECIPES[role]
    write_new(root / f"{role}-training-entered.json", seal({"schema": "d148.training_entry.v1", "role": role, "recipe_digest": frozen["digest"], "fixture_digest": fixture["digest"], "read_partitions": ["train", "validation"]}))
    x = torch.tensor(standardized(train_data, fixture["preprocessing"]), dtype=torch.float64)
    y = torch.tensor(train_data["labels"], dtype=torch.float64).reshape(-1, 1)
    vx = torch.tensor(standardized(validation, fixture["preprocessing"]), dtype=torch.float64)
    vy = torch.tensor(validation["labels"], dtype=torch.float64).reshape(-1, 1)
    model = build(role)
    optimizer = torch.optim.Adam(model.parameters(), lr=recipe["learning_rate"])
    loss = torch.nn.BCEWithLogitsLoss()
    history, best, best_state, selected = [], float("inf"), None, None
    for epoch in range(1, recipe["epochs"] + 1):
        model.train()
        optimizer.zero_grad()
        train_loss = loss(model(x), y)
        train_loss.backward()
        optimizer.step()
        model.eval()
        with torch.no_grad():
            validation_loss = float(loss(model(vx), vy))
        history.append({"epoch": epoch, "train_bce": float(train_loss.detach()), "validation_bce": validation_loss})
        if validation_loss < best:
            best, best_state, selected = validation_loss, copy.deepcopy(model.state_dict()), epoch
    model.load_state_dict(best_state)
    record = checkpoint(role, model, fixture, history, selected)
    validate_checkpoint(record, role, fixture)
    write_new(root / f"{role}-checkpoint.json", record)
    return record
