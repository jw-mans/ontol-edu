"""
Генераторы вариантов: детерминизм, эталон запросом, реестр.

Главное, что здесь проверяется, --- не «вариант породился», а два свойства, на
которых держится вся схема: вариант воспроизводим по сиду (иначе журнал,
хранящий только сид, бесполезен) и эталон вычисляется запросом к онтологии
(иначе он разойдётся с базой при первой же правке).
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from discrete import CYRILLIC, Content, load_content
from discrete.variants import (
    REGISTRY,
    GeneratorContext,
    QueryExpectation,
    ValueExpectation,
    Variant,
    VariantError,
    generate,
    generate_many,
    generator_name,
    register,
    task_node,
)

V = CYRILLIC

SCHEMA_TDL = f"""
КЛАСС {V.unit} АБСТРАКТНЫЙ
  АТРИБУТЫ
    + {V.slot_code} : Строка
КОНЕЦ КЛАСС

КЛАСС {V.concept}
КОНЕЦ КЛАСС

КЛАСС {V.statement} АБСТРАКТНЫЙ
КОНЕЦ КЛАСС

КЛАСС {V.theorem}
КОНЕЦ КЛАСС

КЛАСС {V.proof}
КОНЕЦ КЛАСС

КЛАСС {V.proof_step}
КОНЕЦ КЛАСС

КЛАСС {V.task}
  АТРИБУТЫ
    + {V.slot_code} : Строка
    + {V.slot_generator} : Строка
КОНЕЦ КЛАСС

ОБОБЩЕНИЕ {V.concept} -> {V.unit}
ОБОБЩЕНИЕ {V.statement} -> {V.unit}
ОБОБЩЕНИЕ {V.proof} -> {V.unit}
ОБОБЩЕНИЕ {V.theorem} -> {V.statement}

КОМПОЗИЦИЯ
  {V.proof} 1
  --
  {V.proof_step} *

АССОЦИАЦИЯ
  {V.unit} *
  --
  {V.unit} * : {V.role_requires}

АССОЦИАЦИЯ
  {V.proof} 1
  --
  {V.statement} 1 : {V.role_proves}

АССОЦИАЦИЯ
  {V.proof_step} *
  --
  {V.unit} * : {V.role_justified_by}

АССОЦИАЦИЯ
  {V.task} *
  --
  {V.unit} * : {V.role_checks}
"""

RECORDS_TDL = f"""
КЛАСС основа
  АТРИБУТЫ
    + {V.slot_code} : Строка = "к_1"
КОНЕЦ КЛАСС

КЛАСС среднее
  АТРИБУТЫ
    + {V.slot_code} : Строка = "к_2"
КОНЕЦ КЛАСС

КЛАСС вершина
  АТРИБУТЫ
    + {V.slot_code} : Строка = "к_3"
КОНЕЦ КЛАСС

КЛАСС докВершины
КОНЕЦ КЛАСС

КЛАСС шагА
КОНЕЦ КЛАСС

ЗАВИСИМОСТЬ основа -> {V.concept} экземпляр
ЗАВИСИМОСТЬ среднее -> {V.concept} экземпляр
ЗАВИСИМОСТЬ вершина -> {V.theorem} экземпляр
ЗАВИСИМОСТЬ докВершины -> {V.proof} экземпляр
ЗАВИСИМОСТЬ шагА -> {V.proof_step} экземпляр

АССОЦИАЦИЯ
  среднее 1
  --
  основа 1 : {V.role_requires}

АССОЦИАЦИЯ
  вершина 1
  --
  среднее 1 : {V.role_requires}

АССОЦИАЦИЯ
  докВершины 1
  --
  вершина 1 : {V.role_proves}

КОМПОЗИЦИЯ
  докВершины 1
  --
  шагА 1

АССОЦИАЦИЯ
  шагА 1
  --
  среднее 1 : {V.role_justified_by}
"""

TASKS_TDL = f"""
КЛАСС задВсе
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_1"
    + {V.slot_generator} : Строка = "предпосылки"
КОНЕЦ КЛАСС

КЛАСС задПрямые
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_2"
    + {V.slot_generator} : Строка = "прямые_предпосылки"
КОНЕЦ КЛАСС

КЛАСС задДок
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_3"
    + {V.slot_generator} : Строка = "обоснования_доказательства"
КОНЕЦ КЛАСС

КЛАСС задЧисло
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_4"
    + {V.slot_generator} : Строка = "мощность_объединения"
КОНЕЦ КЛАСС

КЛАСС задВид
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_5"
    + {V.slot_generator} : Строка = "вид_записи"
КОНЕЦ КЛАСС

КЛАСС задБезГенератора
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_6"
КОНЕЦ КЛАСС

КЛАСС задНеизвестный
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_7"
    + {V.slot_generator} : Строка = "нет_такого_генератора"
КОНЕЦ КЛАСС

ЗАВИСИМОСТЬ задВсе -> {V.task} экземпляр
ЗАВИСИМОСТЬ задПрямые -> {V.task} экземпляр
ЗАВИСИМОСТЬ задДок -> {V.task} экземпляр
ЗАВИСИМОСТЬ задЧисло -> {V.task} экземпляр
ЗАВИСИМОСТЬ задВид -> {V.task} экземпляр
ЗАВИСИМОСТЬ задБезГенератора -> {V.task} экземпляр
ЗАВИСИМОСТЬ задНеизвестный -> {V.task} экземпляр
"""


@pytest.fixture()
def content(tmp_path: Path) -> Content:
    """Контент с записями и задачами всех встроенных видов."""
    root = tmp_path / "content"
    root.mkdir()
    (root / "1_schema.tdl").write_text(SCHEMA_TDL, encoding="utf-8")
    (root / "2_records.tdl").write_text(RECORDS_TDL, encoding="utf-8")
    (root / "3_tasks.tdl").write_text(TASKS_TDL, encoding="utf-8")
    return load_content(root)


# ──────────────────────────── эталон ────────────────────────────

def test_query_expectation_is_computed_from_ontology(content: Content) -> None:
    """
    Эталон-запрос вычисляется из базы, а не хранится: правка онтологии меняет
    правильный ответ сама.
    """
    expectation = QueryExpectation(start="вершина", pattern=f"{V.role_requires}+")
    assert expectation.resolve(content.graph) == {"среднее", "основа"}


def test_query_expectation_on_missing_node_is_reported(content: Content) -> None:
    expectation = QueryExpectation(start="нетТакого", pattern=V.role_requires)
    with pytest.raises(VariantError, match="которого нет в контенте"):
        expectation.resolve(content.graph)


def test_value_expectation_requires_a_reason() -> None:
    """
    Правило проекта: хардкод эталона допустим только с объяснением, почему
    запрос не выражает проверку. Пустое объяснение --- ошибка, а не замечание.
    """
    with pytest.raises(ValueError, match="требует reason"):
        ValueExpectation(value=42, reason="")
    with pytest.raises(ValueError, match="требует reason"):
        ValueExpectation(value=42, reason="   ")


def test_value_expectation_with_reason_resolves(content: Content) -> None:
    expectation = ValueExpectation(value=8, reason="ответ --- число, арифметики в запросах нет")
    assert expectation.resolve(content.graph) == 8


# ──────────────────────────── детерминизм ────────────────────────────

def test_same_seed_gives_identical_variant(content: Content) -> None:
    """
    Воспроизводимость --- условие того, что журнал может хранить только сид.
    """
    assert generate(content, "т_4", 7) == generate(content, "т_4", 7)


def test_different_seeds_give_different_variants(content: Content) -> None:
    prompts = {generate(content, "т_4", seed).prompt for seed in range(10)}
    assert len(prompts) > 1


def test_same_seed_differs_across_tasks(content: Content) -> None:
    """
    Сид смешивается с кодом задачи, иначе вариант №1 во всех задачах оказался бы
    порождён одной и той же последовательностью случайных чисел.
    """
    first = generate(content, "т_4", 1)
    # другой код задачи с тем же генератором даёт другую последовательность
    assert first.seed == 1
    assert random.Random("т_4|1").random() != random.Random("т_5|1").random()


def test_generate_many_follows_seed_order(content: Content) -> None:
    variants = generate_many(content, "т_4", (1, 2, 3))
    assert [item.seed for item in variants] == [1, 2, 3]
    assert variants == generate_many(content, "т_4", (1, 2, 3))


def test_pick_is_order_independent(content: Content) -> None:
    """
    Выбор из множества должен не зависеть от порядка обхода: иначе вариант
    перестал бы воспроизводиться между запусками Python.
    """
    context = GeneratorContext(
        task_code="т_1", seed=1, rng=random.Random("т_1|1"),
        content=content, vocabulary=CYRILLIC,
    )
    other = GeneratorContext(
        task_code="т_1", seed=1, rng=random.Random("т_1|1"),
        content=content, vocabulary=CYRILLIC,
    )
    assert context.pick(["б", "а", "в"], "что-то") == other.pick(["в", "а", "б"], "что-то")


def test_pick_without_candidates_is_reported(content: Content) -> None:
    context = GeneratorContext(
        task_code="т_1", seed=1, rng=random.Random("x"),
        content=content, vocabulary=CYRILLIC,
    )
    with pytest.raises(VariantError, match="нет подходящих записей"):
        context.pick([], "запись с предпосылками")


# ──────────────────────── встроенные генераторы ────────────────────────

def test_prerequisites_generator_uses_transitive_closure(content: Content) -> None:
    variant = generate(content, "т_1", seed=1)
    assert isinstance(variant.expectation, QueryExpectation)
    assert variant.expectation.pattern == f"{V.role_requires}+"
    # для «вершина» замыкание даёт обе предпосылки
    if variant.data["запись"] == "вершина":
        assert variant.expected(content.graph) == {"среднее", "основа"}


def test_direct_prerequisites_differ_from_closure(content: Content) -> None:
    """
    Разница «понял транзитивность или нет» выражается сменой паттерна ---
    в этом и смысл того, что эталон формулируется запросом.
    """
    closure = QueryExpectation("вершина", f"{V.role_requires}+")
    direct = QueryExpectation("вершина", V.role_requires)
    assert closure.resolve(content.graph) == {"среднее", "основа"}
    assert direct.resolve(content.graph) == {"среднее"}


def test_proof_justifications_generator(content: Content) -> None:
    variant = generate(content, "т_3", seed=1)
    assert variant.data["доказательство"] == "докВершины"
    assert variant.data["тезис"] == "вершина"
    assert variant.expected(content.graph) == {"среднее"}


def test_classify_record_generator_asks_for_the_class(content: Content) -> None:
    variant = generate(content, "т_5", seed=1)
    assert variant.expectation.pattern == "instanceOf"
    expected = variant.expected(content.graph)
    # эталон --- класс онтологии, экземпляром которого запись является
    assert expected <= {V.concept, V.theorem, V.proof}


def test_classify_record_never_picks_a_task(content: Content) -> None:
    """
    Задачи тоже экземпляры, но содержанием курса не являются: спрашивать
    «какого вида эта запись» про саму задачу бессмысленно.
    """
    for seed in range(20):
        variant = generate(content, "т_5", seed=seed)
        assert variant.data["запись"] not in content.instances_of(V.task)


def test_content_units_excludes_tasks(content: Content) -> None:
    from discrete.variants import content_units
    units = content_units(content)
    assert {"основа", "среднее", "вершина", "докВершины"} <= units
    assert units.isdisjoint(content.instances_of(V.task))


def test_value_generator_carries_a_reason(content: Content) -> None:
    """Задача с числовым ответом обязана объяснить отказ от запроса."""
    variant = generate(content, "т_4", seed=1)
    assert isinstance(variant.expectation, ValueExpectation)
    assert "арифметик" in variant.expectation.reason
    assert variant.answer_kind == "число"
    # эталон согласован с данными варианта
    assert variant.expected(content.graph) == len(
        set(variant.data["A"]) | set(variant.data["B"]))


def test_every_builtin_generator_produces_a_variant(content: Content) -> None:
    for code in ("т_1", "т_2", "т_3", "т_4", "т_5"):
        variant = generate(content, code, seed=3)
        assert isinstance(variant, Variant)
        assert variant.prompt.strip()
        assert variant.task_code == code


# ──────────────────────── связь с онтологией ────────────────────────

def test_task_is_found_by_its_code(content: Content) -> None:
    assert task_node(content, "т_1") == "задВсе"


def test_unknown_task_code_is_reported(content: Content) -> None:
    with pytest.raises(VariantError, match="нет задачи с кодом"):
        task_node(content, "нет_такого_кода")


def test_generator_name_comes_from_the_ontology(content: Content) -> None:
    """
    Слот «генератор» хранит имя функции --- единственное место, где смысл
    осознанно вынесен из графа.
    """
    assert generator_name(content, "т_1") == "предпосылки"


def test_task_without_generator_is_reported(content: Content) -> None:
    with pytest.raises(VariantError, match="не указан слот"):
        generator_name(content, "т_6")


def test_unregistered_generator_is_reported(content: Content) -> None:
    with pytest.raises(VariantError, match="не зарегистрирован"):
        generate(content, "т_7", seed=1)


# ──────────────────────────── реестр ────────────────────────────

def test_registry_holds_builtin_generators() -> None:
    assert {"предпосылки", "прямые_предпосылки", "обоснования_доказательства",
            "вид_записи", "мощность_объединения"} <= set(REGISTRY)


def test_duplicate_registration_is_refused() -> None:
    with pytest.raises(VariantError, match="уже зарегистрирован"):
        register("предпосылки")(lambda context: None)


def test_generator_returning_wrong_type_is_reported(content: Content,
                                                    monkeypatch) -> None:
    monkeypatch.setitem(REGISTRY, "предпосылки", lambda context: "не вариант")
    with pytest.raises(VariantError, match="ожидался Variant"):
        generate(content, "т_1", seed=1)
