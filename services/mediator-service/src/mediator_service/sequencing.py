from __future__ import annotations

from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    depends_on: tuple[str, ...]
    position: int


class SequencingError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateTaskError(SequencingError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} appears more than once in this tree")
        self.task_id = task_id


class UnknownTaskError(SequencingError):
    def __init__(self, task_id: str, context: str) -> None:
        super().__init__(f"unknown task {task_id}: {context}")
        self.task_id = task_id
        self.context = context


class SelfDependencyError(SequencingError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} declares itself as a dependency")
        self.task_id = task_id


class BranchDependencyError(SequencingError):
    def __init__(self, task_id: str, dependency_id: str) -> None:
        super().__init__(
            f"task {task_id} depends on {dependency_id}, which lies on its own branch; "
            "a task cannot wait for its own ancestors or descendants"
        )
        self.task_id = task_id
        self.dependency_id = dependency_id


class ParentCycleError(SequencingError):
    def __init__(self, cycle: tuple[str, ...]) -> None:
        super().__init__(f"parent links form a cycle: {' -> '.join(cycle)}")
        self.cycle = cycle


class DependencyCycleError(SequencingError):
    def __init__(self, cycle: tuple[str, ...], lowered: bool) -> None:
        where = "once dependencies are lowered to leaves" if lowered else "as declared"
        super().__init__(f"dependencies form a cycle {where}: {' -> '.join(cycle)}")
        self.cycle = cycle
        self.lowered = lowered


class Ordering:
    def __init__(self, order: tuple[str, ...], graph: nx.DiGraph) -> None:
        self._order = order
        self._graph = graph

    @property
    def order(self) -> tuple[str, ...]:
        return self._order

    @property
    def leaves(self) -> frozenset[str]:
        return frozenset(self._order)

    def dependencies(self, task_id: str) -> tuple[str, ...]:
        if task_id not in self._graph:
            raise UnknownTaskError(task_id, "not a leaf of this tree")

        predecessors = set(self._graph.predecessors(task_id))
        return tuple(item for item in self._order if item in predecessors)

    def blocked_by(self, task_id: str, settled: frozenset[str]) -> tuple[str, ...]:
        self._assert_known(settled)
        return tuple(item for item in self.dependencies(task_id) if item not in settled)

    def ready(self, settled: frozenset[str]) -> tuple[str, ...]:
        self._assert_known(settled)
        return tuple(
            task_id
            for task_id in self._order
            if task_id not in settled
            and all(item in settled for item in self._graph.predecessors(task_id))
        )

    def next_task(self, settled: frozenset[str]) -> str | None:
        available = self.ready(settled)
        return available[0] if available else None

    def _assert_known(self, settled: frozenset[str]) -> None:
        for task_id in sorted(settled):
            if task_id not in self._graph:
                raise UnknownTaskError(task_id, "reported settled but is not a leaf of this tree")


def _cycle(graph: nx.DiGraph) -> tuple[str, ...] | None:
    try:
        edges = list(nx.find_cycle(graph))
    except nx.NetworkXNoCycle:
        return None

    path = [str(edges[0][0])]

    for edge in edges:
        path.append(str(edge[1]))

    return tuple(path)


def _index(nodes: list[Node]) -> dict[str, Node]:
    index: dict[str, Node] = {}

    for node in nodes:
        if node.id in index:
            raise DuplicateTaskError(node.id)

        index[node.id] = node

    return index


def _tree(index: dict[str, Node]) -> nx.DiGraph:
    tree = nx.DiGraph()
    tree.add_nodes_from(index)

    for node in index.values():
        if node.parent_id is None:
            continue

        if node.parent_id not in index:
            raise UnknownTaskError(node.parent_id, f"named as the parent of {node.id}")

        tree.add_edge(node.parent_id, node.id)

    cycle = _cycle(tree)

    if cycle is not None:
        raise ParentCycleError(cycle)

    return tree


def _assert_declared(index: dict[str, Node]) -> None:
    declared = nx.DiGraph()
    declared.add_nodes_from(index)

    for node in index.values():
        for dependency_id in node.depends_on:
            if dependency_id == node.id:
                raise SelfDependencyError(node.id)

            if dependency_id not in index:
                raise UnknownTaskError(dependency_id, f"named as a dependency of {node.id}")

            declared.add_edge(dependency_id, node.id)

    cycle = _cycle(declared)

    if cycle is not None:
        raise DependencyCycleError(cycle, lowered=False)


def _leaves(tree: nx.DiGraph) -> frozenset[str]:
    return frozenset(str(item) for item in tree if tree.out_degree(item) == 0)


def _subtree_leaves(tree: nx.DiGraph, leaves: frozenset[str], task_id: str) -> frozenset[str]:
    if task_id in leaves:
        return frozenset({task_id})

    return frozenset(str(item) for item in nx.descendants(tree, task_id) if str(item) in leaves)


def _assert_branches(tree: nx.DiGraph, leaves: frozenset[str], index: dict[str, Node]) -> None:
    for node in index.values():
        own = _subtree_leaves(tree, leaves, node.id)

        for dependency_id in node.depends_on:
            if own & _subtree_leaves(tree, leaves, dependency_id):
                raise BranchDependencyError(node.id, dependency_id)


def _lower(tree: nx.DiGraph, leaves: frozenset[str], index: dict[str, Node]) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(leaves))

    for node in index.values():
        targets = _subtree_leaves(tree, leaves, node.id)

        for dependency_id in node.depends_on:
            for source in _subtree_leaves(tree, leaves, dependency_id):
                for target in targets:
                    graph.add_edge(source, target)

    return graph


def _document_keys(index: dict[str, Node]) -> dict[str, tuple[tuple[int, ...], str]]:
    keys: dict[str, tuple[tuple[int, ...], str]] = {}

    for task_id, node in index.items():
        positions: list[int] = []
        current: Node | None = node

        while current is not None:
            positions.append(current.position)
            current = index[current.parent_id] if current.parent_id is not None else None

        keys[task_id] = (tuple(reversed(positions)), task_id)

    return keys


def build(nodes: list[Node]) -> Ordering:
    index = _index(nodes)
    tree = _tree(index)
    _assert_declared(index)

    leaves = _leaves(tree)
    _assert_branches(tree, leaves, index)

    graph = _lower(tree, leaves, index)
    cycle = _cycle(graph)

    if cycle is not None:
        raise DependencyCycleError(cycle, lowered=True)

    keys = _document_keys(index)
    order = tuple(
        str(item)
        for item in nx.lexicographical_topological_sort(graph, key=lambda item: keys[str(item)])
    )

    return Ordering(order, graph)
