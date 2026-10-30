"""
Маленькая синтетическая онтология --- вход для тестов движка запросов.

Движок :mod:`ontol.query` ничего не знает о предметной области: он читает
``ClassDiagram`` по duck typing и работает с помеченным графом. Поэтому для его
тестов не нужна никакая реальная метамодель --- нужна диаграмма, в которой
встречаются ВСЕ виды рёбер и структурные особенности, которые движок обязан
уметь обходить:

- ``gen``        --- иерархия в три уровня, с двумя детьми у одного родителя
                     (это даёт «одно поколение» для CFPQ);
- ``comp``       --- цепочка композиций глубины 4 (для запросов ``comp comp comp``);
- ``aggr``       --- агрегация (альтернатива метки в паттерне ``(comp | aggr)*``);
- ``use``        --- зависимость со стереотипом (метка = стереотип);
- ``real``       --- реализация интерфейса;
- роль ассоциации --- метка ребра при ``role_labels=True``;
- ``instanceOf`` --- на отдельной диаграмме экземпляров.

Предметно это набросок онтологии дискретной математики (понятие / определение /
утверждение / задача), но ЦЕНА его здесь --- только структура графа: тесты
движка не зависят от того, как в итоге будет выглядеть настоящая онтология.

Схема ``build_synthetic_ontology``::

    NamedElement (abstract)
         ^
         | gen
    ContentUnit (abstract)
      ^     ^        ^        ^
      |gen  |gen     |gen     |gen
    Concept Definition Statement(abstract) Task
                          ^      ^
                          |gen   |gen
                      Theorem   Lemma

    Course --comp--> Topic --comp--> Concept --comp--> Definition --comp--> Term
    Task   --aggr--> Statement
    Task   --checks--> Concept          (роль ассоциации)
    Definition --use--> Concept         (стереотип зависимости)
    Theorem    --use--> Definition
    Statement  --real--> Printable      (интерфейс)
    Theorem    --comp--> Proof
    Proof      --comp--> ProofStep

    DifficultyLevel, ProofMethod --- <<enumeration>>
"""
from __future__ import annotations

from uml_dsl.diagram import ClassDiagram
from uml_dsl.enums import AggregationKind, DependencyStereotype, Stereotype
from uml_dsl.models import Attribute, Class
from uml_dsl.relationships import Association, AssociationEnd

from ontol.instances import InstanceDiagram

#: Имена классов онтологии --- чтобы тесты не рассыпались по строковым литералам.
NAMED_ELEMENT = "NamedElement"
CONTENT_UNIT = "ContentUnit"
CONCEPT = "Concept"
DEFINITION = "Definition"
STATEMENT = "Statement"
THEOREM = "Theorem"
LEMMA = "Lemma"
TASK = "Task"
COURSE = "Course"
TOPIC = "Topic"
TERM = "Term"
PROOF = "Proof"
PROOF_STEP = "ProofStep"
PRINTABLE = "Printable"
DIFFICULTY_LEVEL = "DifficultyLevel"
PROOF_METHOD = "ProofMethod"

#: Все классификаторы синтетической онтологии (16 штук).
ALL_CLASSES = frozenset({
    NAMED_ELEMENT, CONTENT_UNIT, CONCEPT, DEFINITION, STATEMENT, THEOREM,
    LEMMA, TASK, COURSE, TOPIC, TERM, PROOF, PROOF_STEP, PRINTABLE,
    DIFFICULTY_LEVEL, PROOF_METHOD,
})

#: Абстрактные классы онтологии.
ABSTRACT_CLASSES = frozenset({NAMED_ELEMENT, CONTENT_UNIT, STATEMENT})

#: Классы со стереотипом ``enumeration``.
ENUMERATIONS = frozenset({DIFFICULTY_LEVEL, PROOF_METHOD})


def build_synthetic_ontology() -> ClassDiagram:
    """
    Собрать синтетическую онтологию как диаграмму классов ONTOL.

    :return: диаграмма классов (вход для :func:`ontol.query.diagram_to_graph`)
    """
    d = ClassDiagram(title="Синтетическая онтология (вход для тестов запросов)")

    named = Class(name=NAMED_ELEMENT, is_abstract=True,
                  attributes=[Attribute(name="name")])
    unit = Class(name=CONTENT_UNIT, is_abstract=True,
                 attributes=[Attribute(name="level")])
    concept = Class(name=CONCEPT, attributes=[Attribute(name="title")])
    definition = Class(name=DEFINITION)
    statement = Class(name=STATEMENT, is_abstract=True)
    theorem = Class(name=THEOREM)
    lemma = Class(name=LEMMA)
    task = Class(name=TASK, attributes=[Attribute(name="level", initial_value="1")])
    course = Class(name=COURSE)
    topic = Class(name=TOPIC)
    term = Class(name=TERM)
    proof = Class(name=PROOF)
    proof_step = Class(name=PROOF_STEP)
    printable = Class(name=PRINTABLE, stereotype=Stereotype.INTERFACE)
    difficulty = Class(name=DIFFICULTY_LEVEL, stereotype=Stereotype.ENUMERATION)
    method = Class(name=PROOF_METHOD, stereotype=Stereotype.ENUMERATION)

    for c in (named, unit, concept, definition, statement, theorem, lemma, task,
              course, topic, term, proof, proof_step, printable, difficulty, method):
        d.add_classifier(c)

    # обобщения: потомок -> предок
    d.add_generalization(CONTENT_UNIT, NAMED_ELEMENT)
    d.add_generalization(CONCEPT, CONTENT_UNIT)
    d.add_generalization(DEFINITION, CONTENT_UNIT)
    d.add_generalization(STATEMENT, CONTENT_UNIT)
    d.add_generalization(TASK, CONTENT_UNIT)
    d.add_generalization(THEOREM, STATEMENT)
    d.add_generalization(LEMMA, STATEMENT)

    # композиции: целое -> часть (цепочка глубины 4 от Course)
    for whole, part in ((COURSE, TOPIC), (TOPIC, CONCEPT),
                        (CONCEPT, DEFINITION), (DEFINITION, TERM),
                        (THEOREM, PROOF), (PROOF, PROOF_STEP)):
        d.add_aggregation(whole, part, aggregation_kind=AggregationKind.COMPOSITION)

    # агрегация: задача собирает утверждения, но не владеет ими
    d.add_aggregation(TASK, STATEMENT, aggregation_kind=AggregationKind.AGGREGATION)

    # зависимости: метка ребра = стереотип зависимости
    d.add_dependency(DEFINITION, CONCEPT, stereotype=DependencyStereotype.USE)
    d.add_dependency(THEOREM, DEFINITION, stereotype=DependencyStereotype.USE)

    # реализация интерфейса
    d.add_realization(STATEMENT, PRINTABLE)

    # обычная ассоциация с ролью: задача проверяет понятие
    d.add_association(Association(ends=[
        AssociationEnd(participant=task, aggregation=AggregationKind.NONE),
        AssociationEnd(participant=concept, role="checks",
                       aggregation=AggregationKind.NONE),
    ]))
    return d


def build_synthetic_instances() -> ClassDiagram:
    """
    Собрать диаграмму экземпляров синтетической онтологии.

    Экземпляры объявляются через :class:`ontol.instances.InstanceDiagram`, то
    есть ровно тем же способом, каким будет наполняться настоящая база: коробка
    ``имя : Класс`` плюс зависимость «instanceOf» к классу онтологии.

    :return: диаграмма классов с рёбрами ``instanceOf``
    """
    concept = Class(name=CONCEPT)
    definition = Class(name=DEFINITION)
    theorem = Class(name=THEOREM)

    d = InstanceDiagram("Экземпляры синтетической онтологии")
    graph = d.instance(concept, "Graph", level="1")
    tree = d.instance(concept, "Tree", level="2")
    bipartite = d.instance(concept, "Bipartite", level="2")
    acyclic = d.instance(definition, "acyclic", kind="formal")
    konig = d.instance(theorem, "Konig", method="induction")

    d.compose(graph, acyclic)          # у понятия Graph есть определение acyclic
    d.link(tree, graph, role="specializes")
    d.link(bipartite, graph, role="specializes")
    d.link(konig, bipartite, role="about")
    return d.build()
