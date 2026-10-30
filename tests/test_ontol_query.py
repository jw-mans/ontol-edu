"""
Язык запросов к ONTOL: RPQ и CFPQ над диаграммой классов (не трогая ядро uml_dsl).

Вход --- синтетическая онтология из :mod:`tests.synthetic_ontology`, собранная
средствами самого ядра. Движок :mod:`ontol.query` предметно-независим
(``diagram_to_graph`` читает диаграмму по duck typing), поэтому его тесты
намеренно НЕ опираются ни на какую прикладную метамодель: смена настоящей
онтологии дискретной математики не должна ронять тесты движка.

Фикстуры ``ontology``/``graph``/``rev_graph``/``instances_graph`` --- в
``tests/conftest.py``.
"""
from __future__ import annotations

import pytest

from uml_dsl.diagram import ClassDiagram
from uml_dsl.models import Class
from uml_dsl.relationships import Generalization

from ontol.instances import InstanceDiagram, instance_of
from ontol.query import (
    LabeledGraph,
    ancestors,
    by_stereotype,
    cfpq,
    descendants,
    diagram_to_graph,
    find_cycles,
    has_attribute,
    has_cycle,
    is_abstract,
    name_contains,
    nodes,
    parse_grammar,
    parse_pattern,
    query,
    reachable_set,
    rpq,
    rpq_reachable,
    select,
)
from tests.synthetic_ontology import ABSTRACT_CLASSES, ALL_CLASSES, ENUMERATIONS


# ─────────────────────────── построение графа ───────────────────────────

def test_graph_labels_and_size(graph: LabeledGraph) -> None:
    assert len(graph.nodes) == 16
    assert graph.nodes == set(ALL_CLASSES)
    # все виды связей онтологии стали метками рёбер
    assert graph.labels() == {"gen", "comp", "aggr", "real", "use", "checks"}


def test_edge_directions(graph: LabeledGraph) -> None:
    assert ("Theorem", "gen", "Statement") in graph.edges       # потомок -> предок
    assert ("Concept", "comp", "Definition") in graph.edges     # целое -> часть
    assert ("Task", "aggr", "Statement") in graph.edges
    assert ("Statement", "real", "Printable") in graph.edges    # класс -> интерфейс
    assert ("Definition", "use", "Concept") in graph.edges      # client -> supplier


def test_association_role_becomes_label(ontology: ClassDiagram) -> None:
    # при role_labels=True роль полюса --- метка ребра, иначе обычный assoc
    assert ("Task", "checks", "Concept") in \
        diagram_to_graph(ontology, role_labels=True).edges
    plain = diagram_to_graph(ontology, role_labels=False)
    assert ("Task", "assoc", "Concept") in plain.edges
    assert "checks" not in plain.labels()


def test_reverse_edges_double_the_graph(ontology: ClassDiagram) -> None:
    direct = diagram_to_graph(ontology)
    rev = diagram_to_graph(ontology, with_reverse=True)
    assert ("Entity" not in rev.nodes) and rev.nodes == direct.nodes
    assert ("Statement", "gen", "ContentUnit") in rev.edges
    assert ("ContentUnit", "gen_rev", "Statement") in rev.edges
    assert len(rev.edges) == 2 * len(direct.edges)


def test_node_attributes_are_queryable(graph: LabeledGraph) -> None:
    assert graph.node_attrs["NamedElement"]["abstract"] is True
    assert graph.node_attrs["Printable"]["stereotype"] == "interface"
    assert graph.node_attrs["Task"]["attributes"] == ["level"]
    assert graph.slot("Task", "level") == "1"
    assert graph.slot("Task", "нет-такого", "по умолчанию") == "по умолчанию"


def test_graph_accessors(graph: LabeledGraph) -> None:
    assert ("gen", "Statement") in graph.out("Theorem")
    assert graph.out_by("Theorem", "gen") == ["Statement"]
    assert graph.one("Theorem", "comp") == "Proof"
    assert graph.one("Theorem", "real") is None
    assert graph.out("НетТакогоУзла") == []


# ─────────────────────────── наследование ───────────────────────────

def test_inheritance_ancestors_descendants(graph: LabeledGraph) -> None:
    assert rpq_reachable(graph, "Theorem", "gen", "Statement")
    assert ancestors(graph, "Theorem") == {"Statement", "ContentUnit", "NamedElement"}
    assert descendants(graph, "Statement") == {"Theorem", "Lemma"}
    assert "Concept" not in descendants(graph, "Statement")
    # корень иерархии: предков нет, потомки --- все содержательные классы
    assert ancestors(graph, "NamedElement") == set()
    assert descendants(graph, "ContentUnit") == {
        "Concept", "Definition", "Statement", "Task", "Theorem", "Lemma",
    }


def test_no_inheritance_cycle_in_ontology(graph: LabeledGraph) -> None:
    assert find_cycles(graph, "gen") == []
    assert not has_cycle(graph, "gen")


def test_composition_query(graph: LabeledGraph) -> None:
    # один шаг композиции
    assert rpq_reachable(graph, "Course", "comp") == {"Topic"}
    assert rpq_reachable(graph, "Theorem", "comp") == {"Proof"}
    # достижимость по композиции произвольной глубины (цепочка из 4 звеньев)
    assert reachable_set(graph, "Course", "comp") == \
        {"Topic", "Concept", "Definition", "Term"}


def test_aggregation_is_separate_label(graph: LabeledGraph) -> None:
    # агрегация не считается композицией и наоборот
    assert rpq_reachable(graph, "Task", "aggr") == {"Statement"}
    assert rpq_reachable(graph, "Task", "comp") == set()


# ─────────────────────── instanceOf на диаграмме экземпляров ───────────────────────

def test_instance_of_query(instances_graph: LabeledGraph) -> None:
    assert "instanceOf" in instances_graph.labels()
    pairs = rpq(instances_graph, "instanceOf")
    assert ("Graph : Concept", "Concept") in pairs
    assert ("acyclic : Definition", "Definition") in pairs
    concepts = {src for src, dst in pairs if dst == "Concept"}
    assert concepts == {"Graph : Concept", "Tree : Concept", "Bipartite : Concept"}


def test_instance_structure_is_queryable(instances_graph: LabeledGraph) -> None:
    # экземпляры связаны между собой так же, как классы онтологии
    assert rpq_reachable(instances_graph, "Graph : Concept", "comp") == \
        {"acyclic : Definition"}
    assert rpq_reachable(instances_graph, "Tree : Concept", "specializes") == \
        {"Graph : Concept"}


# ─────────────────────────── регэксп-паттерны ───────────────────────────

def test_pattern_parsing_and_rpq(graph: LabeledGraph) -> None:
    # разбор регэкспа над метками
    assert parse_pattern("gen+") == ("plus", ("lbl", "gen"))
    assert parse_pattern("a b") == ("seq", ("lbl", "a"), ("lbl", "b"))
    assert parse_pattern("a|b") == ("alt", ("lbl", "a"), ("lbl", "b"))
    assert parse_pattern("gen?") == ("opt", ("lbl", "gen"))
    assert parse_pattern("(comp | aggr)+") == (
        "plus", ("alt", ("lbl", "comp"), ("lbl", "aggr")),
    )
    # альтернатива меток: достижимость по композиции ИЛИ агрегации
    assert rpq_reachable(graph, "Task", "(comp | aggr)*") == {"Task", "Statement"}
    assert rpq_reachable(graph, "Course", "(comp | aggr)+") == \
        {"Topic", "Concept", "Definition", "Term"}


def test_pattern_parsing_of_node_atoms() -> None:
    assert parse_pattern("@Statement") == ("node", None, "Statement")
    assert parse_pattern("@level=2") == ("node", "level", "2")
    assert parse_pattern("@meta=Concept") == ("node", "meta", "Concept")


@pytest.mark.parametrize("bad", [
    "gen %",     # недопустимый символ
    "(gen",      # незакрытая скобка
    "gen)",      # лишние символы в конце
    "@",         # нет имени после @
    "@level=",   # нет значения после =
    "| gen",     # нет левой части альтернативы
    "*",         # квантор без атома
])
def test_malformed_patterns_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_pattern(bad)


def test_prebuilt_ast_is_accepted(graph: LabeledGraph) -> None:
    assert rpq_reachable(graph, "Theorem", parse_pattern("gen+")) == \
        rpq_reachable(graph, "Theorem", "gen+")


def test_empty_and_star_patterns(graph: LabeledGraph) -> None:
    # gen* включает саму вершину (ноль шагов)
    assert "Theorem" in rpq_reachable(graph, "Theorem", "gen*")
    # gen+ не включает вершину, если нет цикла
    assert "Theorem" not in rpq_reachable(graph, "Theorem", "gen+")
    # заданный dst превращает запрос в предикат достижимости
    assert rpq_reachable(graph, "Theorem", "gen+", dst="NamedElement") is True
    assert rpq_reachable(graph, "Theorem", "gen+", dst="Concept") is False


def test_sequence_of_different_labels(graph: LabeledGraph) -> None:
    # зависимость use, затем сколько угодно наследований
    assert rpq_reachable(graph, "Theorem", "use gen*") == \
        {"Definition", "ContentUnit", "NamedElement"}
    # комбинация видов связей: от задачи через агрегацию к потомкам утверждения
    assert nodes(graph, "aggr gen_rev") == set()  # обратных рёбер в графе нет


# ─────────────────── узловые атомы (именованные узлы) ───────────────────

def test_node_named_atoms(graph: LabeledGraph) -> None:
    # узлы именуются прямо в паттерне: @Имя, @слот=значение, @meta=Метакласс
    # кто наследует узел с именем Statement
    assert {s for s, d in rpq(graph, "gen @Statement")} == {"Theorem", "Lemma"}
    # предок узла Theorem по gen --- узел Statement
    assert {d for s, d in rpq(graph, "@Theorem gen")} == {"Statement"}
    # @имя как чистый узловой запрос выделяет сам узел
    assert nodes(graph, "@Lemma") == {"Lemma"}
    # узловой атом сцеплен с меткой: из Theorem по gen в узел с именем Statement
    assert rpq_reachable(graph, "Theorem", "gen @Statement") == {"Statement"}
    # несуществующее имя --- пусто
    assert rpq(graph, "gen @Nonexistent") == set()


def test_node_atom_matches_short_name_of_instance(instances_graph: LabeledGraph) -> None:
    # коробка названа "Graph : Concept"; атом ловит и полное, и короткое имя
    assert nodes(instances_graph, "instanceOf* @Graph") == {"Graph : Concept"}
    assert nodes(instances_graph, "instanceOf* @Concept") == {"Concept"}


def test_node_atom_by_slot(instances_graph: LabeledGraph) -> None:
    assert nodes(instances_graph, "instanceOf* @level=1") == {"Graph : Concept"}
    assert nodes(instances_graph, "instanceOf* @level=2") == \
        {"Tree : Concept", "Bipartite : Concept"}
    assert nodes(instances_graph, "instanceOf* @method=induction") == {"Konig : Theorem"}
    assert nodes(instances_graph, "instanceOf* @level=99") == set()


def test_node_atom_by_metaclass(instances_graph: LabeledGraph) -> None:
    assert nodes(instances_graph, "instanceOf* @meta=Concept") == \
        {"Graph : Concept", "Tree : Concept", "Bipartite : Concept"}
    assert nodes(instances_graph, "instanceOf* @meta=Definition") == \
        {"acyclic : Definition"}
    assert nodes(instances_graph, "instanceOf* @meta=Нет") == set()


def test_node_atom_does_not_consume_edge(instances_graph: LabeledGraph) -> None:
    # атом --- эпсилон-переход с проверкой узла, ребро он не съедает
    assert rpq_reachable(instances_graph, "Tree : Concept",
                         "specializes @meta=Concept") == {"Graph : Concept"}
    # проверка в середине пути отсекает путь целиком
    assert rpq_reachable(instances_graph, "Tree : Concept",
                         "specializes @level=1 comp") == {"acyclic : Definition"}
    assert rpq_reachable(instances_graph, "Tree : Concept",
                         "specializes @level=2 comp") == set()


# ─────────────────── обнаружение цикла наследования ───────────────────

def test_cycle_detection_synthetic() -> None:
    d = ClassDiagram(title="cycle")
    a, b, c = Class(name="A"), Class(name="B"), Class(name="C")
    for x in (a, b, c):
        d.add_classifier(x)
    # A -> B -> C -> A (цикл наследования)
    d.generalizations.extend([
        Generalization(specific=a, general=b),
        Generalization(specific=b, general=c),
        Generalization(specific=c, general=a),
    ])
    g = diagram_to_graph(d)
    assert has_cycle(g, "gen")
    assert set(find_cycles(g, "gen")) == {"A", "B", "C"}


def test_cycle_report_excludes_nodes_merely_leading_into_cycle() -> None:
    g = LabeledGraph()
    for src, dst in (("A", "B"), ("B", "C"), ("C", "A")):
        g.add_edge(src, "gen", dst)
    g.add_edge("D", "gen", "A")  # D ведёт в цикл, но сам на нём не лежит
    assert find_cycles(g, "gen") == ["A", "B", "C"]


# ─────────────────── запросы с предикатами узлов ───────────────────

def test_node_predicates_and_query_filters(graph: LabeledGraph) -> None:
    assert select(graph, is_abstract(graph)) == set(ABSTRACT_CLASSES)
    assert select(graph, by_stereotype(graph, "enumeration")) == set(ENUMERATIONS)
    assert select(graph, by_stereotype(graph, "interface")) == {"Printable"}
    assert select(graph, has_attribute(graph, "level")) == {"ContentUnit", "Task"}
    assert select(graph, name_contains("Proof")) == {"Proof", "ProofStep", "ProofMethod"}
    # запрос с фильтром цели: кто наследует Statement
    inh = {s for s, d in query(graph, "gen", dst="Statement")}
    assert inh == {"Theorem", "Lemma"}
    # запрос с фильтром источника-предиката: обобщения, идущие ИЗ абстрактных классов
    assert query(graph, "gen", src=is_abstract(graph)) == {
        ("ContentUnit", "NamedElement"), ("Statement", "ContentUnit"),
    }


def test_query_without_filters_equals_rpq(graph: LabeledGraph) -> None:
    assert query(graph, "gen+") == rpq(graph, "gen+")


def test_query_combines_both_end_filters(graph: LabeledGraph) -> None:
    # из конкретных классов по наследованию в абстрактные
    pairs = query(graph, "gen+",
                  src=lambda n: not is_abstract(graph)(n),
                  dst=is_abstract(graph))
    assert ("Theorem", "NamedElement") in pairs
    assert all(s not in ABSTRACT_CLASSES and d in ABSTRACT_CLASSES for s, d in pairs)


# ─────────────────── CFPQ (контекстно-свободные запросы) ───────────────────

def test_grammar_parsing() -> None:
    prods, nts = parse_grammar("S -> gen S gen_rev | eps")
    assert nts == {"S"}
    assert ("S", ("gen", "S", "gen_rev")) in prods
    assert ("S", ()) in prods


def test_grammar_parsing_skips_comments() -> None:
    prods, nts = parse_grammar("""
        # «одно поколение»
        S -> gen S gen_rev | eps

    """)
    assert nts == {"S"} and len(prods) == 2


def test_grammar_without_arrow_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_grammar("S gen S")


def test_cfpq_same_generation(rev_graph: LabeledGraph) -> None:
    # S -> gen S gen_rev | eps  : пары с общим предком на одинаковой глубине
    pairs = cfpq(rev_graph, "S -> gen S gen_rev\nS ->", "S")
    assert ("Theorem", "Lemma") in pairs    # оба на 1 уровень ниже Statement
    assert ("Theorem", "Theorem") in pairs  # рефлексивно (eps)
    # Concept, Definition, Statement, Task --- дети ContentUnit, одно поколение
    assert ("Concept", "Statement") in pairs
    assert ("Task", "Definition") in pairs
    # Theorem на уровень ниже Concept --- это НЕ одно поколение
    assert ("Theorem", "Concept") not in pairs


def test_cfpq_nested_composition_depth(rev_graph: LabeledGraph) -> None:
    # ровно два и ровно три уровня композиции из Course
    two = {v for u, v in cfpq(rev_graph, "S -> comp comp", "S") if u == "Course"}
    assert two == {"Concept"}
    three = {v for u, v in cfpq(rev_graph, "S -> comp comp comp", "S") if u == "Course"}
    assert three == {"Definition"}


def test_cfpq_matrix_matches_hellings(rev_graph: LabeledGraph) -> None:
    # матричный движок (Азимов--Григорьев) == Хеллингс, и оба понимают 'eps'
    for grammar in ("S -> gen S gen_rev\nS ->",
                    "S -> comp comp comp",
                    "S -> comp comp | eps"):
        m = cfpq(rev_graph, grammar, "S", method="matrix")
        h = cfpq(rev_graph, grammar, "S", method="hellings")
        assert m == h, grammar
    # 'eps' и пустая правая часть эквивалентны
    assert cfpq(rev_graph, "S -> gen S gen_rev | eps", "S") == \
        cfpq(rev_graph, "S -> gen S gen_rev\nS ->", "S")


def test_cfpq_grammar_normalisation_long_rhs(graph: LabeledGraph) -> None:
    # правило длиной 4 требует и бинаризации, и вынесения терминалов
    four = {v for u, v in cfpq(graph, "S -> comp comp comp comp", "S")
            if u == "Course"}
    assert four == {"Term"}  # Course -> Topic -> Concept -> Definition -> Term


def test_cfpq_start_symbol_selection(rev_graph: LabeledGraph) -> None:
    grammar = "S -> gen S gen_rev | eps\nT -> gen"
    # явный стартовый нетерминал
    assert cfpq(rev_graph, grammar, start="T") == \
        {(s, t) for s, lab, t in rev_graph.edges if lab == "gen"}
    # по умолчанию --- левая часть первого правила
    assert cfpq(rev_graph, grammar) == cfpq(rev_graph, grammar, start="S")


def test_cfpq_unknown_start_is_empty(rev_graph: LabeledGraph) -> None:
    assert cfpq(rev_graph, "S -> gen", start="НЕТ") == set()


def test_cfpq_on_empty_graph() -> None:
    assert cfpq(LabeledGraph(), "S -> gen S gen_rev | eps") == set()


# ───────── режим имён экземпляров, пригодный для записи в TDL ─────────

def test_qualified_names_are_default() -> None:
    """По умолчанию имя коробки --- в нотации UML ``имя : Метакласс``."""
    meta = Class(name="Понятие")
    d = InstanceDiagram("по умолчанию")
    d.instance(meta, "граф", уровень="1")
    g = diagram_to_graph(d.build())
    assert g.nodes == {"Понятие", "граф : Понятие"}


def test_plain_names_survive_queries() -> None:
    """
    ``qualified=False`` даёт имена-идентификаторы, и все узловые атомы
    продолжают работать: принадлежность классу несёт ребро ``instanceOf``,
    а не имя коробки.
    """
    meta = Class(name="Понятие")
    d = InstanceDiagram("TDL-совместимо", qualified=False)
    d.instance(meta, "граф", уровень="1")
    g = diagram_to_graph(d.build())

    assert g.nodes == {"Понятие", "граф"}
    assert ("граф", "instanceOf", "Понятие") in g.edges
    assert nodes(g, "instanceOf* @meta=Понятие") == {"граф"}
    assert nodes(g, "instanceOf* @граф") == {"граф"}
    assert nodes(g, "instanceOf* @уровень=1") == {"граф"}


def test_plain_names_are_parseable_by_tdl() -> None:
    """
    Смысл режима: такие имена записываются в TDL, а квалифицированные --- нет.
    Двоеточие не входит в идентификатор TDL (``ParseError``), поэтому хранить
    экземпляры в TDL можно только при ``qualified=False``.
    """
    from uml_dsl.tdl_lexer import lex
    from uml_dsl.tdl_parser import ParseError, parse_tdl

    parse_tdl(lex("КЛАСС граф\nКОНЕЦ КЛАСС\n"))          # не бросает
    with pytest.raises(ParseError):
        parse_tdl(lex("КЛАСС граф : Понятие\nКОНЕЦ КЛАСС\n"))


def test_instance_of_qualified_flag() -> None:
    """Флаг действует и на низкоуровневой функции."""
    meta = Class(name="Понятие")
    box_q, dep_q = instance_of(meta, "граф")
    box_p, dep_p = instance_of(meta, "граф", qualified=False)
    assert box_q.name == "граф : Понятие"
    assert box_p.name == "граф"
    # связь «instanceOf» в обоих случаях одна и та же
    assert dep_q.supplier.name == dep_p.supplier.name == "Понятие"
