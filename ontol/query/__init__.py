"""
Запросы к путям над ONTOL-моделью (диаграммой классов) как над помеченным графом.

- :mod:`ontol.query.graph` --- перевод ``ClassDiagram`` в помеченный граф;
- :mod:`ontol.query.query` --- регулярные запросы к путям (RPQ) с узловыми атомами;
- :mod:`ontol.query.cfpq`  --- контекстно-свободные запросы к путям (CFPQ).
"""
from .graph import Edge, LabeledGraph, diagram_to_graph
from .query import (
    ancestors,
    by_stereotype,
    descendants,
    find_cycles,
    has_attribute,
    has_cycle,
    is_abstract,
    name_contains,
    nodes,
    parse_pattern,
    query,
    reachable_set,
    rpq,
    rpq_reachable,
    select,
)
from .cfpq import cfpq, parse_grammar

__all__ = [
    # graph
    "Edge",
    "LabeledGraph",
    "diagram_to_graph",
    # RPQ
    "parse_pattern",
    "rpq",
    "rpq_reachable",
    "nodes",
    "query",
    "reachable_set",
    "ancestors",
    "descendants",
    "find_cycles",
    "has_cycle",
    "select",
    "by_stereotype",
    "is_abstract",
    "name_contains",
    "has_attribute",
    # CFPQ
    "parse_grammar",
    "cfpq",
]
