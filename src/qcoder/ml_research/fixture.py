"""Exact fixture materialization; selection APIs expose training/validation only."""
from pathlib import Path

from . import FAMILY, FIXTURE
from .contracts import checked, numeric, read, require, seal, write_new
from qcoder.focused_loop.canonical import canonical_digest


def materialize(root):
    import numpy as np
    from sklearn.datasets import make_moons
    from sklearn.model_selection import train_test_split

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    x, y = make_moons(n_samples=200, noise=0.15, random_state=314159)
    train, rest = train_test_split(np.arange(200), test_size=80, stratify=y, random_state=271828)
    validation, test = train_test_split(rest, test_size=40, stratify=y[rest], random_state=271828)
    splits = {"train": train.tolist(), "validation": validation.tolist(), "test": test.tolist()}
    means, scales = x[train].mean(axis=0), x[train].std(axis=0, ddof=0)
    preprocessing = seal({"schema": "d148.preprocessing.v1", "fit_partition": "train", "train_ids_digest": canonical_digest(splits["train"]), "means": means.tolist(), "scales": scales.tolist(), "ddof": 0})
    partition_records = {}
    for name, indices in splits.items():
        record = seal({"schema": "d148.partition.v1", "partition": name, "ids": indices, "features": x[indices].tolist(), "labels": y[indices].tolist()})
        write_new(root / f"{name}.json", record)
        partition_records[name] = record
    manifest = seal({"schema": "d148.fixture.v1", "fixture": FIXTURE, "family": FAMILY, "generator": {"name": "sklearn.make_moons", "n_samples": 200, "noise": 0.15, "seed": 314159, "split_seed": 271828}, "data_digest": canonical_digest(x.tolist()), "labels_digest": canonical_digest(y.tolist()), "split_digest": canonical_digest(splits), "partitions": {name: record["digest"] for name, record in partition_records.items()}, "preprocessing": preprocessing})
    write_new(root / "fixture.json", manifest)
    return manifest


def manifest(root):
    record = read(Path(root) / "fixture.json")
    checked(record, "d148.fixture.v1", ["fixture", "family", "generator", "data_digest", "labels_digest", "split_digest", "partitions", "preprocessing"])
    require(record["fixture"] == FIXTURE and record["family"] == FAMILY, "fixture_family")
    prep = checked(record["preprocessing"], "d148.preprocessing.v1", ["fit_partition", "train_ids_digest", "means", "scales", "ddof"])
    require(prep["fit_partition"] == "train" and prep["ddof"] == 0, "preprocessing_fit")
    numeric(prep["means"], [2]); numeric(prep["scales"], [2])
    require(all(s > 0 for s in prep["scales"]), "preprocessing_scale")
    return record


def partition(root, name, fixture):
    require(name in ("train", "validation", "test"), "partition_name")
    record = read(Path(root) / f"{name}.json")
    checked(record, "d148.partition.v1", ["partition", "ids", "features", "labels"])
    require(record["digest"] == fixture["partitions"][name] and record["partition"] == name, "partition_mismatch")
    n = 120 if name == "train" else 40
    numeric(record["features"], [n, 2])
    require(len(record["ids"]) == n and len(set(record["ids"])) == n and all(type(i) is int and 0 <= i < 200 for i in record["ids"]), "partition_ids")
    require(len(record["labels"]) == n and all(type(y) is int and y in (0, 1) for y in record["labels"]), "partition_labels")
    return record


def selection_data(root):
    """This function never opens the held-out partition."""
    import numpy as np
    fixture = manifest(root)
    train = partition(root, "train", fixture)
    valid = partition(root, "validation", fixture)
    prep = fixture["preprocessing"]
    require(not set(train["ids"]) & set(valid["ids"]), "split_overlap")
    require(canonical_digest(train["ids"]) == prep["train_ids_digest"], "train_fit_identity")
    require(np.array_equal(np.array(train["features"]).mean(axis=0), prep["means"]), "train_fit_means")
    require(np.array_equal(np.array(train["features"]).std(axis=0), prep["scales"]), "train_fit_scales")
    return fixture, train, valid


def standardized(record, prep):
    return [[(row[i] - prep["means"][i]) / prep["scales"][i] for i in range(2)] for row in record["features"]]
