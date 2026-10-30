"""
Проверка ответов студента --- запросами к онтологии.

Это то, ради чего построено всё остальное. Эталон здесь не хранится, а
вычисляется: :class:`discrete.variants.QueryExpectation` выполняет запрос в
момент проверки, поэтому правка онтологии меняет правильный ответ сама, и
эталон не может разойтись с базой.

Проверка даёт не вердикт «неверно», а разбор: что пропущено, что лишнее и
какого класса ошибка. Классы ошибок тоже определяются запросами --- например,
«назвал прямые предпосылки, но не транзитивные» видно из того, что ответ
совпал с результатом укороченного паттерна. На этом разборе потом строятся
подсказки (:func:`hint`), и поэтому подсказка не нуждается в языковой модели:
класс ошибки даёт запрос, а текст берётся из шаблона.

Задания «нарисуй диаграмму» проверяются тем же механизмом: SVG
разбирается обратно в модель ядром (``uml_dsl.svg_parser``), модель приводится
к помеченному графу, и к нему применяются те же запросы, что к онтологии.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

from uml_dsl.svg_parser import parse_svg_to_diagram

from ontol.query import Edge, LabeledGraph, diagram_to_graph, find_cycles

from .content import Content
from .journal import Verdict
from .variants import (
    QueryExpectation,
    SubgraphExpectation,
    ValueExpectation,
    Variant,
)

#: Разделители элементов в ответе-перечислении.
_SEPARATORS = re.compile(r"[,;\n\r\t]+")


class CheckError(Exception):
    """Ошибка проверки ответа (не ошибка студента, а сбой проверки)."""


# ДИАГНОЗ 

@dataclass(frozen=True)
class Diagnosis:
    """
    Класс ошибки, определённый запросом.

    :param kind: короткое имя класса ошибки --- к нему привязан шаблон подсказки
    :param message: человеческое описание
    :param nodes: конкретные узлы, из-за которых поставлен диагноз
    """

    kind: str
    message: str
    nodes: Tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f" [{', '.join(self.nodes)}]" if self.nodes else ""
        return f"{self.kind}: {self.message}{where}"


@dataclass(frozen=True)
class CheckResult:
    """
    Разбор ответа: вердикт плюс всё, что нужно для подсказки и журнала.

    :param verdict: итог проверки
    :param expected: эталонный ответ (вычисленный, не хранимый)
    :param actual: ответ студента после разбора
    :param missing: что студент пропустил
    :param extra: что назвал лишнего
    :param diagnoses: классы ошибок
    """

    verdict: Verdict
    expected: Any
    actual: Any
    missing: FrozenSet[str] = frozenset()
    extra: FrozenSet[str] = frozenset()
    diagnoses: Tuple[Diagnosis, ...] = ()

    @property
    def correct(self) -> bool:
        """Ответ полностью верен."""
        return self.verdict is Verdict.CORRECT

    def as_details(self) -> Dict[str, Any]:
        """
        Разбор в виде, пригодном для журнала (JSON-сериализуемый).

        :return: словарь для :meth:`discrete.journal.Journal.record_attempt`
        """
        return {
            "пропущено": sorted(self.missing),
            "лишние": sorted(self.extra),
            "диагнозы": [
                {"класс": item.kind, "узлы": list(item.nodes)}
                for item in self.diagnoses
            ],
        }


# РАЗБОР ОТВЕТА

def parse_set_answer(raw: str) -> Set[str]:
    """
    Разобрать ответ-перечисление в множество имён.

    Терпимо к оформлению: разделители --- запятая, точка с запятой, перевод
    строки, табуляция; лишние пробелы и пустые элементы отбрасываются. Регистр
    и порядок не важны --- важен состав, поэтому ответ приводится к множеству.

    :param raw: ответ студента как есть

    :return: множество названных элементов
    """
    return {
        item.strip() for item in _SEPARATORS.split(raw or "") if item.strip()
    }


def parse_number_answer(raw: str) -> Optional[float]:
    """
    Разобрать числовой ответ.

    :param raw: ответ студента

    :return: число либо ``None``, если ответ не разбирается как число
    """
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_diagram_answer(raw: str) -> LabeledGraph:
    """
    Разобрать ответ-диаграмму: SVG --> модель --> помеченный граф.

    Разбор делает ядро (``uml_dsl.svg_parser``); дальше работает тот же
    ``diagram_to_graph``, что и для онтологии, поэтому к ответу применимы те же
    запросы.

    :param raw: содержимое SVG

    :return: граф нарисованной студентом диаграммы

    :raises CheckError: SVG не разбирается
    """
    result = parse_svg_to_diagram(raw or "")
    if not result.success or result.diagram is None:
        reasons = "; ".join(result.errors) or "неизвестная причина"
        raise CheckError(f"Диаграмма не разбирается: {reasons}")
    return diagram_to_graph(result.diagram, role_labels=True)


# ДИАГНОСТИКА: ПЕРЕЧИСЛЕНИЕ

def _shorten(pattern: str) -> Optional[str]:
    """
    Укоротить паттерн замыкания до одного шага: ``"требует+"`` -> ``"требует"``.

    Нужно, чтобы отличить «не понял транзитивность» от просто неполного
    ответа: если ответ студента в точности равен результату укороченного
    паттерна, он сделал один шаг вместо замыкания.

    :param pattern: исходный паттерн

    :return: укороченный паттерн либо ``None``, если укоротить нечего
    """
    text = pattern.strip()
    if text.endswith("+") and not text.endswith(")+"):
        return text[:-1].strip() or None
    return None


def diagnose_set(variant: Variant, expected: Set[str], actual: Set[str],
                 content: Content) -> Tuple[Diagnosis, ...]:
    """
    Определить классы ошибок в ответе-перечислении --- запросами.

    :param variant: проверяемый вариант
    :param expected: эталонный ответ
    :param actual: ответ студента
    :param content: загруженный контент

    :return: кортеж диагнозов (может быть пустым)
    """
    graph = content.graph
    missing = expected - actual
    extra = actual - expected
    found: List[Diagnosis] = []

    # Назвал то, чего в базе нет вообще: опечатка или выдумка.
    unknown = sorted(item for item in extra if item not in graph.nodes)
    if unknown:
        found.append(Diagnosis(
            "неизвестная_запись",
            "в базе нет записей с такими именами --- возможно, опечатка",
            tuple(unknown),
        ))

    # Ответ совпал с результатом укороченного запроса: один шаг вместо
    # замыкания, то есть транзитивность не учтена.
    if missing and isinstance(variant.expectation, QueryExpectation):
        shorter = _shorten(variant.expectation.pattern)
        if shorter:
            direct = QueryExpectation(variant.expectation.start, shorter)
            if actual and actual == direct.resolve(graph):
                found.append(Diagnosis(
                    "не_учтена_транзитивность",
                    "перечислено только то, на что запись опирается напрямую; "
                    "предпосылки предпосылок тоже входят в ответ",
                    tuple(sorted(missing)),
                ))

    # Лишнее того же вида, что пропущенное: записи спутаны между собой.
    confused: List[str] = []
    for item in sorted(extra):
        if item not in graph.nodes:
            continue
        kind = graph.one(item, "instanceOf")
        if kind and any(graph.one(gap, "instanceOf") == kind for gap in missing):
            confused.append(item)
    if confused:
        found.append(Diagnosis(
            "спутаны_однотипные",
            "названы записи того же вида, что пропущенные --- похоже, "
            "перепутаны между собой",
            tuple(confused),
        ))

    # Остальное лишнее: есть в базе, но в ответ не входит.
    irrelevant = sorted(
        item for item in extra
        if item in graph.nodes and item not in confused
    )
    if irrelevant:
        found.append(Diagnosis(
            "лишнее_в_ответе",
            "эти записи существуют, но в ответ на этот вопрос не входят",
            tuple(irrelevant),
        ))

    # Неполный, но без лишнего ответ --- отдельный случай: студент на верном
    # пути, и подсказка должна отличаться от «ответ неверен».
    if missing and not extra and not found:
        found.append(Diagnosis(
            "ответ_неполон",
            "всё названное верно, но перечислено не всё",
            tuple(sorted(missing)),
        ))
    return tuple(found)


# ДИАГНОСТИКА: ДИАГРАММА

def diagnose_diagram(expected: Set[Edge], actual: LabeledGraph,
                     labels: Sequence[str]) -> Tuple[Diagnosis, ...]:
    """
    Определить классы ошибок в нарисованной диаграмме --- запросами к её графу.

    Каждый класс ошибки --- отдельный вопрос к графу ответа, а не сравнение
    картинок: перевёрнутая стрелка видна как наличие обратного ребра, подмена
    вида связи --- как ребро с другой меткой между теми же узлами.

    :param expected: эталонные рёбра
    :param actual: граф диаграммы студента
    :param labels: метки связей, которые требовалось нарисовать

    :return: кортеж диагнозов
    """
    found: List[Diagnosis] = []
    expected_nodes = {node for source, _, target in expected for node in (source, target)}
    drawn = {
        (source, label, target) for source, label, target in actual.edges
        if label in labels
    }

    # Цикл по наследованию --- заведомо некорректная диаграмма.
    cycles = find_cycles(actual, "gen")
    if cycles:
        found.append(Diagnosis(
            "цикл_наследования",
            "классы образуют цикл по обобщению --- так иерархия построена быть "
            "не может",
            tuple(cycles),
        ))

    # Узлы.
    missing_nodes = sorted(expected_nodes - actual.nodes)
    if missing_nodes:
        found.append(Diagnosis(
            "пропущен_класс", "этих классов на диаграмме нет",
            tuple(missing_nodes),
        ))
    extra_nodes = sorted(actual.nodes - expected_nodes)
    if extra_nodes:
        found.append(Diagnosis(
            "лишний_класс", "эти классы на диаграмме лишние",
            tuple(extra_nodes),
        ))

    # Перевёрнутая связь: нарисовано обратное ребро вместо требуемого.
    reversed_edges = sorted(
        f"{source}->{target}" for source, label, target in expected - drawn
        if (target, label, source) in drawn
    )
    if reversed_edges:
        found.append(Diagnosis(
            "перевёрнутая_связь",
            "связь нарисована в обратную сторону",
            tuple(reversed_edges),
        ))

    # Подменён вид связи: между теми же узлами стоит ребро с другой меткой.
    wrong_kind = sorted(
        f"{source}->{target}" for source, label, target in expected - drawn
        if any(other != label and (source, other, target) in set(actual.edges)
               for other in actual.labels())
    )
    if wrong_kind:
        found.append(Diagnosis(
            "подменён_вид_связи",
            "между этими классами нарисована связь другого вида",
            tuple(wrong_kind),
        ))

    # Остальные недостающие и лишние связи.
    accounted = set(reversed_edges) | set(wrong_kind)
    missing_edges = sorted(
        f"{source}->{target}" for source, label, target in expected - drawn
        if f"{source}->{target}" not in accounted
    )
    if missing_edges:
        found.append(Diagnosis(
            "пропущена_связь", "этих связей на диаграмме нет",
            tuple(missing_edges),
        ))
    extra_edges = sorted(
        f"{source}->{target}" for source, label, target in drawn - expected
        if (target, label, source) not in expected
    )
    if extra_edges:
        found.append(Diagnosis(
            "лишняя_связь", "этих связей в ответе быть не должно",
            tuple(extra_edges),
        ))
    return tuple(found)


# ПРОВЕРКА

def _verdict(expected: Set[Any], actual: Set[Any]) -> Verdict:
    """
    Вердикт по составу множеств.

    :param expected: эталон
    :param actual: ответ студента

    :return: вердикт
    """
    if not actual:
        return Verdict.SKIPPED
    if actual == expected:
        return Verdict.CORRECT
    if actual < expected:          # всё верно, но не всё названо
        return Verdict.PARTIAL
    return Verdict.INCORRECT


def check(variant: Variant, raw_answer: str, content: Content) -> CheckResult:
    """
    Проверить ответ студента на вариант задания.

    Вид проверки определяется типом эталона: запрос к онтологии даёт множество,
    подграф --- рёбра диаграммы, готовое значение --- число либо строку.

    :param variant: выданный вариант
    :param raw_answer: ответ студента как есть
    :param content: загруженный контент

    :return: разбор ответа

    :raises CheckError: ответ принципиально не разбирается (например, битый SVG)
    """
    expectation = variant.expectation

    if isinstance(expectation, SubgraphExpectation):
        expected_edges = expectation.resolve(content.graph)
        if not (raw_answer or "").strip():
            return CheckResult(Verdict.SKIPPED, expected_edges, None)
        drawn = parse_diagram_answer(raw_answer)
        labels = expectation.labels
        actual_edges = {
            edge for edge in drawn.edges if edge[1] in labels
        }
        diagnoses = diagnose_diagram(expected_edges, drawn, labels)
        verdict = Verdict.CORRECT if actual_edges == expected_edges and not diagnoses \
            else _verdict(expected_edges, actual_edges)
        return CheckResult(
            verdict=verdict,
            expected=expected_edges,
            actual=actual_edges,
            missing=frozenset(f"{s}->{t}" for s, _, t in expected_edges - actual_edges),
            extra=frozenset(f"{s}->{t}" for s, _, t in actual_edges - expected_edges),
            diagnoses=diagnoses,
        )

    if isinstance(expectation, ValueExpectation):
        expected_value = expectation.resolve(content.graph)
        if isinstance(expected_value, (int, float)):
            actual_value = parse_number_answer(raw_answer)
            if actual_value is None:
                return CheckResult(
                    Verdict.SKIPPED if not (raw_answer or "").strip()
                    else Verdict.INCORRECT,
                    expected_value, raw_answer,
                    diagnoses=() if not (raw_answer or "").strip() else (
                        Diagnosis("не_число", "ожидался числовой ответ"),
                    ),
                )
            verdict = (Verdict.CORRECT if float(expected_value) == actual_value
                       else Verdict.INCORRECT)
            return CheckResult(verdict, expected_value, actual_value)
        # нечисловое значение --- сравнение строк после нормализации пробелов
        normalised = " ".join((raw_answer or "").split())
        verdict = (Verdict.SKIPPED if not normalised else
                   Verdict.CORRECT if normalised == str(expected_value)
                   else Verdict.INCORRECT)
        return CheckResult(verdict, expected_value, normalised)

    if isinstance(expectation, QueryExpectation):
        expected_set = expectation.resolve(content.graph)
        actual_set = parse_set_answer(raw_answer)
        verdict = _verdict(expected_set, actual_set)
        diagnoses = (() if verdict in (Verdict.CORRECT, Verdict.SKIPPED)
                     else diagnose_set(variant, expected_set, actual_set, content))
        return CheckResult(
            verdict=verdict,
            expected=expected_set,
            actual=actual_set,
            missing=frozenset(expected_set - actual_set),
            extra=frozenset(actual_set - expected_set),
            diagnoses=diagnoses,
        )

    raise CheckError(
        f"Неизвестный вид эталона: {type(expectation).__name__}"
    )


# ПОДСКАЗКИ

#: Шаблоны подсказок по классу ошибки. Класс определяет ЗАПРОС, текст берётся
#: отсюда --- поэтому подсказка детерминирована и её можно прочитать заранее.
HINT_TEMPLATES: Mapping[str, str] = {
    "не_учтена_транзитивность":
        "Вы перечислили только прямые предпосылки. Посмотрите, на что опираются "
        "они сами --- это тоже часть ответа.",
    "спутаны_однотипные":
        "Среди названного есть записи того же вида, что нужные. Проверьте, те ли "
        "именно вы выбрали.",
    "неизвестная_запись":
        "Некоторых названных записей в базе нет --- проверьте написание.",
    "лишнее_в_ответе":
        "Часть названного к этому вопросу не относится.",
    "ответ_неполон":
        "Всё названное верно, но перечислено не всё.",
    "не_число":
        "Ответом должно быть число.",
    "цикл_наследования":
        "В иерархии получился цикл: класс оказался собственным предком.",
    "перевёрнутая_связь":
        "Одна из связей нарисована в обратную сторону. Наследование ведёт от "
        "потомка к предку, композиция --- от целого к части.",
    "подменён_вид_связи":
        "Между этими классами нужна связь другого вида.",
    "пропущен_класс":
        "На диаграмме не хватает классов.",
    "лишний_класс":
        "На диаграмме есть лишние классы.",
    "пропущена_связь":
        "Не хватает связей между классами.",
    "лишняя_связь":
        "Есть связи, которых в ответе быть не должно.",
}


def hint(result: CheckResult, content: Content, level: int = 1) -> Optional[str]:
    """
    Подсказка по разбору ответа, с градацией по уровню.

    Уровни --- это расстояние до прямого ответа, и каждый выражается запросом
    разной глубины: сначала объём недостающего, потом вид пропущенного, и лишь
    затем сами имена. Выдать всё сразу означало бы решить задачу за студента.

    :param result: разбор ответа
    :param content: загруженный контент
    :param level: 1 --- насколько ответ неполон, 2 --- какого вида пропущенное,
        3 --- назвать пропущенное

    :return: текст подсказки либо ``None``, если ответ верен
    """
    if result.correct:
        return None

    # Класс ошибки важнее объёма: он объясняет ПРИЧИНУ, а не симптом.
    for diagnosis in result.diagnoses:
        template = HINT_TEMPLATES.get(diagnosis.kind)
        if template and level == 1:
            return template

    if result.verdict is Verdict.SKIPPED:
        return "Вы не дали ответа."

    if level <= 1:
        if result.missing:
            return f"Ответ неполон: не хватает {len(result.missing)} пункт(ов)."
        if result.extra:
            return f"В ответе {len(result.extra)} лишний(х) пункт(ов)."
        return "Ответ неверен."

    if level == 2 and result.missing:
        # Вид пропущенного берётся запросом: это класс онтологии записи.
        kinds = sorted({
            kind for item in result.missing
            if (kind := content.graph.one(item, "instanceOf")) is not None
        })
        if kinds:
            return f"Среди пропущенного есть: {', '.join(kinds)}."
        return f"Пропущено пунктов: {len(result.missing)}."

    parts: List[str] = []
    if result.missing:
        parts.append(f"не хватает: {', '.join(sorted(result.missing))}")
    if result.extra:
        parts.append(f"лишнее: {', '.join(sorted(result.extra))}")
    return "; ".join(parts) if parts else "Ответ неверен."
