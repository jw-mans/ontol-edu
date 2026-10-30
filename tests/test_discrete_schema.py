"""
Схема онтологии дискретной математики: словарь имён и три профиля.

Проверяется то, от чего зависит весь прикладной слой:

- имена пригодны и для запросов, и для записи в TDL (одиночные идентификаторы);
- каждый profile даёт корректную диаграмму с нужными метками рёбер;
- профили вложены: ``ЗАДАЧИ`` ⊆ ``ПОНЯТИЯ`` ⊆ ``ПОЛНЫЙ`` --- именно это делает
  переключение профиля дешёвым, а контент --- общим для всех трёх.
"""
from __future__ import annotations

import pytest

from uml_dsl.tdl_lexer import lex
from uml_dsl.tdl_parser import parse_tdl

from discrete import CYRILLIC, Profile, Vocabulary, build_schema, reference_class
from discrete.names import IDENTIFIER
from ontol.query import diagram_to_graph, find_cycles, nodes, rpq_reachable


# ──────────────────────────── словарь имён ────────────────────────────

def test_all_names_are_identifiers() -> None:
    """Требование лексера паттернов и лексера TDL (§2.2--2.3 ТЗ)."""
    CYRILLIC.validate()  # не бросает


def test_duplicate_names_rejected() -> None:
    bad_vocab = Vocabulary(**{**vars(CYRILLIC), "concept": CYRILLIC.theorem})
    with pytest.raises(ValueError, match="занято дважды"):
        bad_vocab.validate()


@pytest.mark.parametrize("bad_name", [
    "Единица Контента",   # пробел
    "Единица-Контента",   # дефис
    "Единица.Контента",   # точка
    "граф : Понятие",     # UML-нотация экземпляра
])
def test_non_identifier_names_rejected(bad_name: str) -> None:
    bad_vocab = Vocabulary(**{**vars(CYRILLIC), "unit": bad_name})
    with pytest.raises(ValueError, match="не является одиночным"):
        bad_vocab.validate()
    assert not IDENTIFIER.match(bad_name)


def test_names_are_writable_as_tdl() -> None:
    """Имя класса из словаря должно приниматься лексером TDL как есть."""
    for name in vars(CYRILLIC).values():
        parse_tdl(lex(f"КЛАСС {name}\nКОНЕЦ КЛАСС\n"))  # не бросает


def test_cyrillic_names_work_in_patterns() -> None:
    g = diagram_to_graph(build_schema(Profile.FULL), role_labels=True)
    # роли-метки и имена классов на кириллице адресуются паттерном
    assert nodes(g, f"@{CYRILLIC.theorem}") == {CYRILLIC.theorem}
    assert rpq_reachable(g, CYRILLIC.definition, CYRILLIC.role_defines) == \
        {CYRILLIC.concept}


# ──────────────────────────── полный profile ────────────────────────────

@pytest.fixture()
def full_graph():
    return diagram_to_graph(build_schema(Profile.FULL), role_labels=True)


def test_full_profile_classes(full_graph) -> None:
    v = CYRILLIC
    assert full_graph.nodes == {
        v.unit, v.concept, v.definition, v.statement, v.theorem, v.lemma,
        v.proof, v.proof_step, v.course, v.topic, v.task, v.variant,
        v.difficulty_level, v.answer_kind,
    }


def test_full_profile_edge_labels(full_graph) -> None:
    v = CYRILLIC
    assert full_graph.labels() == {
        "gen", "comp",
        v.role_defines, v.role_requires, v.role_proves,
        v.role_justified_by, v.role_next, v.role_checks,
    }


def test_content_unit_hierarchy(full_graph) -> None:
    v = CYRILLIC
    assert rpq_reachable(full_graph, v.theorem, "gen+") == {v.statement, v.unit}
    # все подвиды содержания сходятся к абстрактной единице контента
    assert rpq_reachable(full_graph, v.definition, "gen") == {v.unit}
    assert full_graph.node_attrs[v.unit]["abstract"] is True
    assert full_graph.node_attrs[v.statement]["abstract"] is True


def test_proof_layer_is_modelled(full_graph) -> None:
    """Решение по §3: доказательства разбираются по шагам."""
    v = CYRILLIC
    assert rpq_reachable(full_graph, v.proof, v.role_proves) == \
        {v.statement}
    assert rpq_reachable(full_graph, v.proof, "comp") == {v.proof_step}
    assert rpq_reachable(full_graph, v.proof_step, v.role_justified_by) == {v.unit}
    assert rpq_reachable(full_graph, v.proof_step, v.role_next) == {v.proof_step}


def test_tasks_are_a_separate_layer(full_graph) -> None:
    v = CYRILLIC
    # задача не является единицей контента, а ссылается на неё
    assert rpq_reachable(full_graph, v.task, "gen+") == set()
    assert rpq_reachable(full_graph, v.task, v.role_checks) == {v.unit}
    assert rpq_reachable(full_graph, v.task, "comp") == {v.variant}


def test_course_structure(full_graph) -> None:
    v = CYRILLIC
    assert rpq_reachable(full_graph, v.course, "comp") == {v.topic}
    assert rpq_reachable(full_graph, v.topic, "comp") == {v.unit}


def test_enumerations_have_stereotype(full_graph) -> None:
    v = CYRILLIC
    for name in (v.difficulty_level, v.answer_kind):
        assert full_graph.node_attrs[name]["stereotype"] == "enumeration"


def test_schema_has_no_inheritance_cycles(full_graph) -> None:
    assert find_cycles(full_graph, "gen") == []


# ──────────────────────── остальные два профиля ────────────────────────

def test_concepts_profile_folds_content() -> None:
    """Единица контента --- понятие; определения и утверждения ушли в слоты."""
    v = CYRILLIC
    g = diagram_to_graph(build_schema(Profile.CONCEPTS), role_labels=True)

    assert g.nodes == {
        v.concept, v.course, v.topic, v.task, v.variant,
        v.difficulty_level, v.answer_kind,
    }
    # отдельных узлов под определение/утверждение/доказательство нет
    for missing in (v.unit, v.definition, v.statement, v.theorem,
                      v.lemma, v.proof, v.proof_step):
        assert missing not in g.nodes
    # зато их содержание доступно как слоты понятия
    slots = g.node_attrs[v.concept]["attributes"]
    assert {v.definition, v.statement, v.proof} <= set(slots)
    # карта знаний сохраняется
    assert rpq_reachable(g, v.concept, v.role_requires) == {v.concept}
    assert rpq_reachable(g, v.task, v.role_checks) == {v.concept}


def test_tasks_profile_has_no_knowledge_map() -> None:
    v = CYRILLIC
    g = diagram_to_graph(build_schema(Profile.TASKS), role_labels=True)

    assert g.nodes == {
        v.course, v.topic, v.task, v.variant, v.difficulty_level, v.answer_kind,
    }
    # ссылаться не на что: ни требует, ни проверяет
    assert g.labels() == {"comp"}
    # тема состоит прямо из задач
    assert rpq_reachable(g, v.topic, "comp") == {v.task}


def test_profiles_are_nested() -> None:
    """
    ``ЗАДАЧИ`` ⊆ ``ПОНЯТИЯ`` ⊆ ``ПОЛНЫЙ``.

    Это ключевое свойство: контент наполняется один раз в полном профиле, а
    переключение профиля отбрасывает слои, не требуя переписывать данные.
    """
    node_sets = {
        profile: diagram_to_graph(build_schema(profile)).nodes
        for profile in Profile
    }
    assert node_sets[Profile.TASKS] < node_sets[Profile.CONCEPTS]
    assert node_sets[Profile.CONCEPTS] < node_sets[Profile.FULL]


def test_reference_class_per_profile() -> None:
    assert reference_class(Profile.FULL) == CYRILLIC.unit
    assert reference_class(Profile.CONCEPTS) == CYRILLIC.concept
    with pytest.raises(ValueError, match="карты знаний нет"):
        reference_class(Profile.TASKS)


def test_query_ports_across_profiles() -> None:
    """
    Один и тот же запрос работает в двух профилях, если имя класса-цели
    берётся из :func:`reference_class`, а не пишется литералом.
    """
    for profile in (Profile.FULL, Profile.CONCEPTS):
        g = diagram_to_graph(build_schema(profile), role_labels=True)
        target = reference_class(profile)
        assert rpq_reachable(g, CYRILLIC.task, CYRILLIC.role_checks) == {target}
        assert rpq_reachable(g, target, CYRILLIC.role_requires) == {target}


def test_all_profiles_pass_core_validation() -> None:
    """Структурная валидация ``uml_dsl`` --- отдельно от наших инвариантов."""
    for profile in Profile:
        build_schema(profile).validate_all()  # не бросает
