#!/usr/bin/env python3
"""Verify the WI-0441 public import boundary without importing qCoder."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

TIER_D = frozenset(
    {
        "qcoder.algorithm_blueprint",
        "qcoder.algorithm_intent_recovery",
        "qcoder.blueprint_decisions",
        "qcoder.context_loop",
        "qcoder.current_loop_adaptive_intent",
        "qcoder.current_loop_coordinator",
        "qcoder.d079_workflows",
    }
)
PRE_CHANGE = {
    "python_modules": 109,
    "internal_import_edges": 304,
    "strongly_connected_components": 83,
    "cyclic_components": 3,
    "largest_component": 25,
}


def _module(path: Path, source: Path) -> str:
    parts = list(path.relative_to(source).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(current: str, level: int, name: str | None) -> str:
    if level == 0:
        return name or ""
    package = current.split(".")[:-1]
    base = package[: max(0, len(package) - level + 1)]
    if name:
        base.extend(name.split("."))
    return ".".join(base)


def _components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    stacked: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        stacked.add(node)
        for neighbor in sorted(graph[node]):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in stacked:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                stacked.remove(item)
                component.append(item)
                if item == node:
                    break
            result.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(result, key=lambda item: (-len(item), item))


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    pending = list(graph[start])
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        pending.extend(graph[item])
    return seen


def analyze(repository: Path) -> dict[str, Any]:
    source = repository / "src"
    paths = sorted((source / "qcoder").rglob("*.py"))
    modules = {_module(path, source): path for path in paths}
    known = set(modules)
    graph: dict[str, set[str]] = {name: set() for name in known}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in known:
                        graph[name].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                target = _resolve(name, node.level, node.module)
                for alias in node.names:
                    child = f"{target}.{alias.name}" if target else alias.name
                    if child in known:
                        graph[name].add(child)
                    elif target in known:
                        graph[name].add(target)
    components = _components(graph)
    cyclic = [item for item in components if len(item) > 1]
    non_facades = sorted(known - TIER_D)
    direct = {name: sorted(graph[name] & TIER_D) for name in non_facades if graph[name] & TIER_D}
    transitive = {
        name: sorted(_reachable(graph, name) & TIER_D)
        for name in non_facades
        if _reachable(graph, name) & TIER_D
    }
    mixed = [item for item in cyclic if set(item) & TIER_D and set(item) - TIER_D]
    hook_imports = sorted(graph["qcoder.cursor_post_write_hook"])
    protected_package_imports = sorted(
        {
            target
            for targets in graph.values()
            for target in targets
            if target.startswith("qcoder_protected")
        }
    )
    result = {
        "schema_id": "qcoder.wi0441.public_boundary_graph.v1",
        "pre_change": PRE_CHANGE,
        "post_change": {
            "python_modules": len(known),
            "internal_import_edges": sum(len(items) for items in graph.values()),
            "strongly_connected_components": len(components),
            "cyclic_components": len(cyclic),
            "largest_component": max(map(len, components), default=0),
        },
        "cyclic_components": cyclic,
        "tier_d_facades": sorted(TIER_D),
        "non_facade_to_tier_d_direct": direct,
        "non_facade_to_tier_d_transitive": transitive,
        "mixed_tier_d_components": mixed,
        "cursor_post_write_hook_direct_imports": hook_imports,
        "cursor_post_write_hook_reaches_tier_d": sorted(
            _reachable(graph, "qcoder.cursor_post_write_hook") & TIER_D
        ),
        "protected_package_imports": protected_package_imports,
    }
    if direct or transitive or mixed:
        raise ValueError("tier_d_boundary_violation")
    if result["cursor_post_write_hook_reaches_tier_d"]:
        raise ValueError("cursor_post_write_hook_boundary_violation")
    if "qcoder.current_loop_coordinator" in hook_imports:
        raise ValueError("cursor_post_write_hook_coordinator_violation")
    if protected_package_imports:
        raise ValueError("private_package_imported_by_public_source")
    if result["post_change"]["largest_component"] >= PRE_CHANGE["largest_component"]:
        raise ValueError("mixed_scc_not_broken")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(analyze(args.repository.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
