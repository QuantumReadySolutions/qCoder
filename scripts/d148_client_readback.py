"""Compatibility alias for the single state-aware Phase E context operation.

New bindings use d148_client_context.py or qcoder.ml_research.client_context.
"""
from qcoder.ml_research.client_context import main

if __name__ == '__main__':
    raise SystemExit(main())
