"""
Общие фикстуры тестов.

Вход тестов движка запросов --- синтетическая онтология из
:mod:`tests.synthetic_ontology`, а не какая-либо прикладная метамодель: движок
:mod:`ontol.query` предметно-независим, и его тесты не должны ломаться при
изменении настоящей онтологии дискретной математики.
"""
from __future__ import annotations

import pytest

from ontol.query import LabeledGraph, diagram_to_graph
from uml_dsl.diagram import ClassDiagram

from tests.synthetic_ontology import (
    build_synthetic_instances,
    build_synthetic_ontology,
)


@pytest.fixture()
def ontology() -> ClassDiagram:
    """Синтетическая онтология как диаграмма классов."""
    return build_synthetic_ontology()


@pytest.fixture()
def graph(ontology: ClassDiagram) -> LabeledGraph:
    """Граф синтетической онтологии (роли ассоциаций --- метками рёбер)."""
    return diagram_to_graph(ontology, role_labels=True)


@pytest.fixture()
def rev_graph(ontology: ClassDiagram) -> LabeledGraph:
    """Граф онтологии с обратными рёбрами ``*_rev`` --- вход для CFPQ."""
    return diagram_to_graph(ontology, with_reverse=True, role_labels=True)


@pytest.fixture()
def instances_graph() -> LabeledGraph:
    """Граф диаграммы экземпляров (рёбра ``instanceOf``)."""
    return diagram_to_graph(build_synthetic_instances(), role_labels=True)
