# Sample circuit corpus

The `train/` directory holds **sample QASM circuits** used for development, experiments, and documentation examples. Filenames follow a legacy benchmark-style convention; they are **not** a shipped training dataset for the `qcoder` CLI.

- **`qcoder analyze`** and **`qcoder batch`** do **not** require these files. Pass paths to your own OpenQASM (or supported) circuit files.
- PyPI wheels and sdists include only the Python package, tests, and docs—this folder is for **repository clones** and local workflows.

Empty sibling directories may appear when you generate local corpora; they are optional.
