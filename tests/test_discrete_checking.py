"""
Проверка ответов студента: разбор, вердикт, диагностика, подсказки.

Главное, что здесь проверяется, --- что проверка опирается на ВЫЧИСЛЯЕМЫЙ
эталон и даёт разбор, а не только вердикт. Класс ошибки должен определяться
запросом: «назвал прямые предпосылки вместо транзитивных» --- это диагноз, из
которого получается осмысленная подсказка, а не просто «неверно».

SVG-ответы берутся из ``tests/data/`` готовыми, чтобы тесты не требовали
установленного Graphviz; отдельный тест проверяет живой круговой путь и
пропускается, если ``dot`` недоступен.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from discrete import CYRILLIC, Content, load_content
from discrete.checking import (
    HINT_TEMPLATES,
    CheckError,
    CheckResult,
    Diagnosis,
    check,
    diagnose_diagram,
    hint,
    parse_diagram_answer,
    parse_number_answer,
    parse_set_answer,
)
from discrete.journal import Verdict
from discrete.variants import (
    QueryExpectation,
    SubgraphExpectation,
    ValueExpectation,
    Variant,
    generate,
)

V = CYRILLIC
DATA = Path(__file__).resolve().parent / "data"

SCHEMA_TDL = f"""
КЛАСС {V.unit} АБСТРАКТНЫЙ
КОНЕЦ КЛАСС

КЛАСС {V.concept}
КОНЕЦ КЛАСС

КЛАСС {V.definition}
КОНЕЦ КЛАСС

КЛАСС {V.statement} АБСТРАКТНЫЙ
КОНЕЦ КЛАСС

КЛАСС {V.theorem}
КОНЕЦ КЛАСС

КЛАСС {V.task}
  АТРИБУТЫ
    + {V.slot_code} : Строка
    + {V.slot_generator} : Строка
КОНЕЦ КЛАСС

ОБОБЩЕНИЕ {V.concept} -> {V.unit}
ОБОБЩЕНИЕ {V.definition} -> {V.unit}
ОБОБЩЕНИЕ {V.statement} -> {V.unit}
ОБОБЩЕНИЕ {V.theorem} -> {V.statement}

АССОЦИАЦИЯ
  {V.unit} *
  --
  {V.unit} * : {V.role_requires}

АССОЦИАЦИЯ
  {V.definition} 1
  --
  {V.concept} 1 : {V.role_defines}

АССОЦИАЦИЯ
  {V.task} *
  --
  {V.unit} * : {V.role_checks}
"""

#: Цепочка: вершина -> среднее -> основа. Плюс однотипные записи для диагноза
#: «спутаны однотипные» и определение, не входящее в ответ.
RECORDS_TDL = f"""
КЛАСС основа
КОНЕЦ КЛАСС
КЛАСС среднее
КОНЕЦ КЛАСС
КЛАСС вершина
КОНЕЦ КЛАСС
КЛАСС двойник
КОНЕЦ КЛАСС
КЛАСС опрОсновы
КОНЕЦ КЛАСС

ЗАВИСИМОСТЬ основа -> {V.concept} экземпляр
ЗАВИСИМОСТЬ среднее -> {V.concept} экземпляр
ЗАВИСИМОСТЬ двойник -> {V.concept} экземпляр
ЗАВИСИМОСТЬ вершина -> {V.theorem} экземпляр
ЗАВИСИМОСТЬ опрОсновы -> {V.definition} экземпляр

АССОЦИАЦИЯ
  среднее 1
  --
  основа 1 : {V.role_requires}

АССОЦИАЦИЯ
  вершина 1
  --
  среднее 1 : {V.role_requires}

АССОЦИАЦИЯ
  опрОсновы 1
  --
  основа 1 : {V.role_defines}
"""

TASKS_TDL = f"""
КЛАСС задВсе
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_1"
    + {V.slot_generator} : Строка = "предпосылки"
КОНЕЦ КЛАСС

КЛАСС задЧисло
  АТРИБУТЫ
    + {V.slot_code} : Строка = "т_4"
    + {V.slot_generator} : Строка = "мощность_объединения"
КОНЕЦ КЛАСС

ЗАВИСИМОСТЬ задВсе -> {V.task} экземпляр
ЗАВИСИМОСТЬ задЧисло -> {V.task} экземпляр
"""


@pytest.fixture()
def content(tmp_path: Path) -> Content:
    root = tmp_path / "content"
    root.mkdir()
    (root / "1_schema.tdl").write_text(SCHEMA_TDL, encoding="utf-8")
    (root / "2_records.tdl").write_text(RECORDS_TDL, encoding="utf-8")
    (root / "3_tasks.tdl").write_text(TASKS_TDL, encoding="utf-8")
    return load_content(root)


@pytest.fixture()
def closure_variant() -> Variant:
    """Задание «все предпосылки вершины» --- эталон считается запросом."""
    return Variant(
        task_code="т_1", seed=1,
        prompt="Назовите всё, на что опирается «вершина».",
        expectation=QueryExpectation("вершина", f"{V.role_requires}+"),
    )


# ──────────────────────────── разбор ответа ────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("основа, среднее", {"основа", "среднее"}),
    ("основа;среднее", {"основа", "среднее"}),
    ("основа\nсреднее", {"основа", "среднее"}),
    ("  основа ,, среднее  ", {"основа", "среднее"}),
    ("основа, основа", {"основа"}),          # повтор не важен
    ("", set()),
    ("   ", set()),
])
def test_parse_set_answer_is_tolerant(raw: str, expected: set) -> None:
    """Важен состав ответа, а не его оформление."""
    assert parse_set_answer(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("8", 8.0), (" 8 ", 8.0), ("8.5", 8.5), ("8,5", 8.5),
    ("", None), ("восемь", None), ("8 элементов", None),
])
def test_parse_number_answer(raw: str, expected) -> None:
    assert parse_number_answer(raw) == expected


# ──────────────────────── эталон вычисляется ────────────────────────

def test_expected_is_computed_not_stored(content: Content,
                                         closure_variant: Variant) -> None:
    """
    Эталон --- результат запроса к онтологии в момент проверки, поэтому он не
    может разойтись с базой.
    """
    result = check(closure_variant, "среднее, основа", content)
    assert result.expected == {"среднее", "основа"}
    assert result.verdict is Verdict.CORRECT


def test_unknown_expectation_kind_is_reported(content: Content) -> None:
    variant = Variant("т_1", 1, "?", expectation=object())
    with pytest.raises(CheckError, match="Неизвестный вид эталона"):
        check(variant, "ответ", content)


# ──────────────────────────── вердикты ────────────────────────────

def test_full_answer_is_correct(content: Content, closure_variant: Variant) -> None:
    assert check(closure_variant, "среднее, основа", content).verdict is Verdict.CORRECT


def test_subset_answer_is_partial(content: Content, closure_variant: Variant) -> None:
    result = check(closure_variant, "среднее", content)
    assert result.verdict is Verdict.PARTIAL
    assert result.missing == frozenset({"основа"})
    assert result.extra == frozenset()


def test_answer_with_extra_is_incorrect(content: Content,
                                        closure_variant: Variant) -> None:
    result = check(closure_variant, "среднее, основа, опрОсновы", content)
    assert result.verdict is Verdict.INCORRECT
    assert result.extra == frozenset({"опрОсновы"})


def test_empty_answer_is_skipped(content: Content, closure_variant: Variant) -> None:
    result = check(closure_variant, "   ", content)
    assert result.verdict is Verdict.SKIPPED
    assert result.diagnoses == ()


# ──────────────────── диагностика: классы ошибок ────────────────────

def test_transitivity_not_understood_is_diagnosed(content: Content,
                                                  closure_variant: Variant) -> None:
    """
    Ключевой диагноз: ответ в точности совпал с результатом УКОРОЧЕННОГО
    паттерна --- студент сделал один шаг вместо замыкания. Это не «неполный
    ответ», а конкретная непонятая идея, и подсказка должна быть другой.
    """
    result = check(closure_variant, "среднее", content)
    kinds = [item.kind for item in result.diagnoses]
    assert "не_учтена_транзитивность" in kinds
    diagnosis = next(d for d in result.diagnoses
                     if d.kind == "не_учтена_транзитивность")
    assert diagnosis.nodes == ("основа",)


def test_incomplete_answer_without_pattern_match(content: Content) -> None:
    """
    Если ответ неполон, но не совпадает с укороченным запросом, диагноз
    другой --- просто неполнота.
    """
    variant = Variant("т_1", 1, "?",
                      expectation=QueryExpectation("вершина", f"{V.role_requires}+"))
    result = check(variant, "основа", content)   # дальняя, но не прямая
    kinds = [item.kind for item in result.diagnoses]
    assert "ответ_неполон" in kinds
    assert "не_учтена_транзитивность" not in kinds


def test_unknown_name_is_diagnosed(content: Content,
                                   closure_variant: Variant) -> None:
    result = check(closure_variant, "среднее, основа, срednee", content)
    diagnosis = next(d for d in result.diagnoses if d.kind == "неизвестная_запись")
    assert diagnosis.nodes == ("срednee",)


def test_confused_same_kind_is_diagnosed(content: Content) -> None:
    """
    Назвал запись того же вида, что пропущенная: вид определяется запросом
    ``instanceOf``, то есть классом онтологии, а не эвристикой по имени.
    """
    variant = Variant("т_1", 1, "?",
                      expectation=QueryExpectation("вершина", f"{V.role_requires}+"))
    # «двойник» --- тоже Понятие, как и пропущенная «основа»
    result = check(variant, "среднее, двойник", content)
    kinds = [item.kind for item in result.diagnoses]
    assert "спутаны_однотипные" in kinds


def test_irrelevant_extra_is_diagnosed(content: Content,
                                       closure_variant: Variant) -> None:
    """«опрОсновы» --- Определение, а пропущено Понятие: это просто лишнее."""
    result = check(closure_variant, "среднее, основа, опрОсновы", content)
    kinds = [item.kind for item in result.diagnoses]
    assert "лишнее_в_ответе" in kinds
    assert "спутаны_однотипные" not in kinds


# ──────────────────────── числовой ответ ────────────────────────

def test_number_answer_checked_against_value(content: Content) -> None:
    variant = Variant(
        "т_4", 1, "Сколько элементов?",
        expectation=ValueExpectation(8, reason="арифметики в запросах нет"),
        answer_kind="число",
    )
    assert check(variant, "8", content).verdict is Verdict.CORRECT
    assert check(variant, "7", content).verdict is Verdict.INCORRECT
    assert check(variant, "", content).verdict is Verdict.SKIPPED


def test_non_numeric_answer_is_diagnosed(content: Content) -> None:
    variant = Variant(
        "т_4", 1, "Сколько элементов?",
        expectation=ValueExpectation(8, reason="арифметики в запросах нет"),
        answer_kind="число",
    )
    result = check(variant, "восемь", content)
    assert result.verdict is Verdict.INCORRECT
    assert [item.kind for item in result.diagnoses] == ["не_число"]


def test_generated_number_variant_is_consistent(content: Content) -> None:
    """Эталон числовой задачи согласован с данными варианта."""
    variant = generate(content, "т_4", seed=5)
    expected = variant.expected(content.graph)
    assert check(variant, str(expected), content).verdict is Verdict.CORRECT


# ──────────────────────── ответ-диаграмма ────────────────────────

@pytest.fixture()
def diagram_variant() -> Variant:
    """Задание «нарисуй фрагмент» --- эталоном служит подграф онтологии."""
    return Variant(
        task_code="т_9", seed=1,
        prompt="Нарисуйте «вершина», её предпосылки и связи «требует».",
        expectation=SubgraphExpectation(
            start="вершина", scope=f"{V.role_requires}*",
            labels=(V.role_requires,),
        ),
        answer_kind="диаграмма",
    )


def test_subgraph_expectation_is_computed_from_ontology(
        content: Content, diagram_variant: Variant) -> None:
    edges = diagram_variant.expectation.resolve(content.graph)
    assert edges == {
        ("вершина", V.role_requires, "среднее"),
        ("среднее", V.role_requires, "основа"),
    }


def test_correct_diagram_is_accepted(content: Content,
                                     diagram_variant: Variant) -> None:
    svg = (DATA / "diagram_correct.svg").read_text(encoding="utf-8")
    result = check(diagram_variant, svg, content)
    assert result.verdict is Verdict.CORRECT
    assert result.diagnoses == ()


def test_reversed_edge_is_diagnosed(content: Content,
                                    diagram_variant: Variant) -> None:
    """
    Перевёрнутая стрелка --- самая частая ошибка на диаграммах, и она видна
    запросом: в графе ответа есть обратное ребро вместо требуемого.
    """
    svg = (DATA / "diagram_reversed.svg").read_text(encoding="utf-8")
    result = check(diagram_variant, svg, content)
    assert result.verdict is not Verdict.CORRECT
    assert "перевёрнутая_связь" in [item.kind for item in result.diagnoses]


def test_missing_class_is_diagnosed(content: Content,
                                    diagram_variant: Variant) -> None:
    svg = (DATA / "diagram_missing_node.svg").read_text(encoding="utf-8")
    result = check(diagram_variant, svg, content)
    kinds = [item.kind for item in result.diagnoses]
    assert "пропущен_класс" in kinds
    assert "основа" in next(
        item for item in result.diagnoses if item.kind == "пропущен_класс").nodes


def test_extra_class_and_edge_are_diagnosed(content: Content,
                                            diagram_variant: Variant) -> None:
    svg = (DATA / "diagram_extra.svg").read_text(encoding="utf-8")
    result = check(diagram_variant, svg, content)
    kinds = [item.kind for item in result.diagnoses]
    assert "лишний_класс" in kinds
    assert "лишняя_связь" in kinds


def test_empty_diagram_answer_is_skipped(content: Content,
                                         diagram_variant: Variant) -> None:
    assert check(diagram_variant, "", content).verdict is Verdict.SKIPPED


def test_broken_svg_is_reported(content: Content,
                                diagram_variant: Variant) -> None:
    with pytest.raises(CheckError, match="не разбирается"):
        check(diagram_variant, "<svg>не та разметка</svg>", content)


def test_inheritance_cycle_is_diagnosed() -> None:
    """Цикл по обобщению --- заведомо некорректная иерархия."""
    from ontol.query import LabeledGraph
    drawn = LabeledGraph()
    for source, target in (("А", "Б"), ("Б", "В"), ("В", "А")):
        drawn.add_edge(source, "gen", target)
    diagnoses = diagnose_diagram(set(), drawn, ("gen",))
    assert "цикл_наследования" in [item.kind for item in diagnoses]


@pytest.mark.skipif(shutil.which("dot") is None
                    and not Path(r"C:\Program Files\Graphviz\bin\dot.exe").exists(),
                    reason="Graphviz не установлен")
def test_live_round_trip_through_svg(content: Content,
                                     diagram_variant: Variant) -> None:
    """
    Живой круговой путь: модель -> SVG (Graphviz) -> модель -> граф -> запрос.
    Именно он обеспечивает проверку заданий «нарисуй диаграмму».
    """
    from uml_dsl.diagram import ClassDiagram
    from uml_dsl.enums import AggregationKind
    from uml_dsl.graphviz_render import diagram_to_graphviz_svg
    from uml_dsl.models import Class
    from uml_dsl.relationships import Association, AssociationEnd

    diagram = ClassDiagram(title="ответ студента")
    classes = {}
    for name in ("вершина", "среднее", "основа"):
        classes[name] = Class(name=name)
        diagram.add_classifier(classes[name])
    for source, target in (("вершина", "среднее"), ("среднее", "основа")):
        diagram.add_association(Association(ends=[
            AssociationEnd(participant=classes[source],
                           aggregation=AggregationKind.NONE),
            AssociationEnd(participant=classes[target], role=V.role_requires,
                           aggregation=AggregationKind.NONE),
        ]))

    svg = diagram_to_graphviz_svg(diagram)
    assert check(diagram_variant, svg, content).verdict is Verdict.CORRECT


# ──────────────────────────── подсказки ────────────────────────────

def test_hint_is_absent_for_correct_answer(content: Content,
                                           closure_variant: Variant) -> None:
    assert hint(check(closure_variant, "среднее, основа", content), content) is None


def test_hint_explains_the_cause_not_the_symptom(content: Content,
                                                 closure_variant: Variant) -> None:
    """
    Подсказка первого уровня объясняет ПРИЧИНУ (класс ошибки), а не просто
    сообщает, что ответ неполон.
    """
    result = check(closure_variant, "среднее", content)
    text = hint(result, content, level=1)
    assert text == HINT_TEMPLATES["не_учтена_транзитивность"]


def test_hint_levels_reveal_progressively(content: Content) -> None:
    """
    Лестница подсказок: объём -> вид пропущенного -> сами имена. Выдать всё
    сразу означало бы решить задачу за студента.
    """
    variant = Variant("т_1", 1, "?",
                      expectation=QueryExpectation("вершина", f"{V.role_requires}+"))
    result = check(variant, "основа", content)      # неполно, без шаблонного класса

    first = hint(result, content, level=1)
    second = hint(result, content, level=2)
    third = hint(result, content, level=3)

    assert "среднее" not in (first or "")            # имя пока не выдано
    assert V.concept in (second or "")               # назван вид пропущенного
    assert "среднее" in (third or "")                # и только теперь имя


def test_hint_for_skipped_answer(content: Content,
                                 closure_variant: Variant) -> None:
    result = check(closure_variant, "", content)
    assert hint(result, content, level=1) == "Вы не дали ответа."


# ──────────────────────── разбор для журнала ────────────────────────

def test_details_are_json_serialisable(content: Content,
                                       closure_variant: Variant) -> None:
    """Разбор уходит в журнал как JSON --- значит обязан сериализоваться."""
    import json

    result = check(closure_variant, "среднее, двойник", content)
    details = result.as_details()
    assert json.loads(json.dumps(details, ensure_ascii=False)) == details
    assert details["пропущено"] == ["основа"]
    assert details["лишние"] == ["двойник"]
    assert details["диагнозы"]


def test_result_flows_into_the_journal(content: Content,
                                       closure_variant: Variant,
                                       tmp_path: Path) -> None:
    """Проверка, журнал и восстановление варианта по сиду работают вместе."""
    from discrete.journal import Journal

    result = check(closure_variant, "среднее", content)
    with Journal(tmp_path / "j.sqlite3") as journal:
        session = journal.start_session("ст-1", content.version)
        issue = journal.issue(session, closure_variant.task_code,
                              closure_variant.seed, content.version)
        journal.record_attempt(issue, "среднее", result.verdict,
                               content.version, result.as_details())
        stored = journal.attempts()[0]

    assert stored.verdict is Verdict.PARTIAL
    assert stored.answer == "среднее"
    assert stored.details["пропущено"] == ["основа"]
