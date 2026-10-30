"""
Генераторы вариантов задач: один шаблон задачи --> много индивидуальных заданий.

Зачем варианты: тренажёр ставится на поток, и один вариант на всех означает
списывание. Вариант порождается ДЕТЕРМИНИРОВАННО по паре «код задачи + сид»,
поэтому в журнале достаточно хранить сид --- само задание восстанавливается
когда угодно.

Главное проектное решение модуля --- в типе эталона. Правило проекта требует
формулировать проверку ЗАПРОСОМ к онтологии везде, где это возможно, а хардкод
допускать лишь там, где запрос принципиально не выражает проверку, и с
объяснением почему. Здесь это закодировано в типах, а не оставлено на
дисциплину автора задачи:

- :class:`QueryExpectation` --- эталон ВЫЧИСЛЯЕТСЯ запросом в момент проверки.
  Такой эталон не может разойтись с базой: поправили онтологию --- ответ
  поменялся сам.
- :class:`ValueExpectation` --- эталон вычислен генератором, и поле ``reason``
  ОБЯЗАТЕЛЬНО: объяснить, почему запрос не подходит. Пустое объяснение ---
  ошибка, а не предупреждение.

Так «посчитай число сочетаний» (арифметика запросом не выражается, §6.3 ТЗ)
останется возможной, но потребует явного обоснования, а «назови предпосылки
теоремы» нельзя будет случайно захардкодить.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Tuple

from ontol.query import Edge, LabeledGraph, nodes, rpq_reachable

from .content import Content
from .names import VOCABULARY, Vocabulary
from .schema import reference_class


class VariantError(Exception):
    """Ошибка порождения варианта."""


# ЭТАЛОН

@dataclass(frozen=True)
class QueryExpectation:
    """
    Эталон как ЗАПРОС к онтологии --- предпочтительный способ.

    Вычисляется в момент проверки, поэтому не может разойтись с базой.

    :param start: узел, из которого идёт запрос
    :param pattern: паттерн RPQ (над метками рёбер и узловыми атомами)
    :param explanation: человеческое описание, что именно спрашивается
    """

    start: str
    pattern: str
    explanation: str = ""

    def resolve(self, graph: LabeledGraph) -> Set[str]:
        """
        Вычислить эталонный ответ запросом.

        :param graph: граф контента

        :return: множество узлов --- правильный ответ

        :raises VariantError: узел запроса отсутствует в графе
        """
        if self.start not in graph.nodes:
            raise VariantError(
                f"Эталон ссылается на узел {self.start!r}, которого нет в контенте"
            )
        return set(rpq_reachable(graph, self.start, self.pattern))


@dataclass(frozen=True)
class ValueExpectation:
    """
    Эталон как готовое значение --- только там, где запрос не применим.

    :param value: правильный ответ
    :param reason: ПОЧЕМУ эталон не выражен запросом; обязательно
    :param explanation: человеческое описание, что именно спрашивается

    :raises ValueError: объяснение не указано
    """

    value: Any
    reason: str
    explanation: str = ""

    def __post_init__(self) -> None:
        if not str(self.reason).strip():
            raise ValueError(
                "ValueExpectation требует reason: объясните, почему проверка не "
                "выражается запросом к онтологии (правило проекта --- проверять "
                "запросом везде, где это возможно)"
            )

    def resolve(self, graph: LabeledGraph) -> Any:
        """
        Вернуть заранее вычисленный эталон.

        :param graph: граф контента (не используется --- значение уже готово)

        :return: эталонный ответ
        """
        return self.value


@dataclass(frozen=True)
class SubgraphExpectation:
    """
    Эталон для задания «нарисуй диаграмму»: набор РЁБЕР, а не узлов.

    Область и состав эталона тоже вычисляются из онтологии: берутся узлы,
    достижимые из ``start`` по ``scope``, и все рёбра между ними с указанными
    метками. Ответ студента (SVG) разбирается обратно в модель, приводится к
    графу и сравнивается с этим набором --- см. :mod:`discrete.checking`.

    :param start: узел, вокруг которого строится эталонный фрагмент
    :param scope: паттерн, задающий область (напр. ``"gen*"``, ``"требует*"``)
    :param labels: метки связей, которые студент обязан нарисовать
    :param explanation: человеческое описание задания
    """

    start: str
    scope: str
    labels: Tuple[str, ...]
    explanation: str = ""

    def area(self, graph: LabeledGraph) -> Set[str]:
        """
        Узлы эталонного фрагмента.

        :param graph: граф контента

        :return: множество узлов области

        :raises VariantError: узел запроса отсутствует в графе
        """
        if self.start not in graph.nodes:
            raise VariantError(
                f"Эталон ссылается на узел {self.start!r}, которого нет в контенте"
            )
        return {self.start} | set(rpq_reachable(graph, self.start, self.scope))

    def resolve(self, graph: LabeledGraph) -> Set[Edge]:
        """
        Вычислить эталонный набор рёбер запросом к онтологии.

        :param graph: граф контента

        :return: множество рёбер ``(источник, метка, приёмник)``
        """
        area = self.area(graph)
        return {
            (source, label, target) for source, label, target in graph.edges
            if label in self.labels and source in area and target in area
        }


#: Эталон варианта: запрос к онтологии, подграф либо готовое значение.
Expectation = Any  # QueryExpectation | SubgraphExpectation | ValueExpectation


# ВАРИАНТ

@dataclass(frozen=True)
class Variant:
    """
    Конкретное задание, выданное студенту.

    :param task_code: код задачи в контенте
    :param seed: сид, по которому вариант воспроизводим
    :param prompt: формулировка с подставленными данными
    :param expectation: эталон (запрос либо значение)
    :param data: данные варианта --- то, что сгенерировано детерминированно
    :param answer_kind: ожидаемый вид ответа (множество/число/диаграмма/…)
    """

    task_code: str
    seed: int
    prompt: str
    expectation: Expectation
    data: Mapping[str, Any] = field(default_factory=dict)
    answer_kind: str = "множество"

    def expected(self, graph: LabeledGraph) -> Any:
        """
        Эталонный ответ: для запроса --- вычисленный, для значения --- готовый.

        :param graph: граф контента

        :return: эталонный ответ
        """
        return self.expectation.resolve(graph)


@dataclass(frozen=True)
class GeneratorContext:
    """
    Всё, что нужно генератору варианта.

    :param task_code: код задачи
    :param seed: сид варианта
    :param rng: засеянный генератор случайных чисел --- ЕДИНСТВЕННЫЙ допустимый
        источник случайности; обращение к ``random`` напрямую сломает
        воспроизводимость
    :param content: загруженный контент (онтология + записи)
    :param vocabulary: словарь имён
    """

    task_code: str
    seed: int
    rng: random.Random
    content: Content
    vocabulary: Vocabulary

    @property
    def graph(self) -> LabeledGraph:
        """Граф контента."""
        return self.content.graph

    def pick(self, candidates: Sequence[str], what: str) -> str:
        """
        Выбрать один элемент детерминированно по сиду.

        :param candidates: варианты выбора (порядок приводится к
            отсортированному --- иначе выбор зависел бы от порядка обхода
            множества и перестал быть воспроизводимым)
        :param what: что выбирается --- для сообщения об ошибке

        :return: выбранный элемент

        :raises VariantError: выбирать не из чего
        """
        ordered = sorted(candidates)
        if not ordered:
            raise VariantError(
                f"В контенте нет подходящих записей, чтобы выбрать {what}"
            )
        return self.rng.choice(ordered)


def content_units(content: Content) -> Set[str]:
    """
    Записи, являющиеся единицами контента (а не задачами и не их частями).

    Отбор формулируется запросом ``instanceOf gen* @<класс-цель>``: запись
    годится, если её класс --- сама единица контента либо её подвид. Это
    отсекает задачи и варианты, которые тоже являются экземплярами, но
    содержанием курса не являются и спрашивать о них «какого ты вида»
    бессмысленно.

    :param content: загруженный контент

    :return: множество имён записей-единиц контента
    """
    target = reference_class(content.profile, content.vocabulary)
    return {
        node for node in content.instances
        if rpq_reachable(content.graph, node, f"instanceOf gen* @{target}")
    }


#: Генератор варианта: из контекста порождает задание.
GeneratorFn = Callable[[GeneratorContext], Variant]

#: Реестр генераторов: имя из слота «генератор» --> функция.
REGISTRY: Dict[str, GeneratorFn] = {}


def register(name: str) -> Callable[[GeneratorFn], GeneratorFn]:
    """
    Зарегистрировать генератор под именем, которое указано в онтологии.

    Слот ``генератор`` у задачи хранит ИМЯ функции, а не код --- это
    единственное место, где смысл осознанно выносится из графа (§4.2
    ``docs/discrete-ontology.md``). Реестр связывает имя с реализацией.

    :param name: имя генератора (значение слота ``генератор``)

    :return: декоратор, регистрирующий функцию

    :raises VariantError: имя уже занято
    """
    def decorate(function: GeneratorFn) -> GeneratorFn:
        if name in REGISTRY:
            raise VariantError(f"Генератор {name!r} уже зарегистрирован")
        REGISTRY[name] = function
        return function
    return decorate


# ВСТРОЕННЫЕ ГЕНЕРАТОРЫ 

# Все они работают с ЛЮБОЙ темой курса: берут записи из онтологии, а эталон
# формулируют запросом. Генераторы, привязанные к конкретным темам, появятся
# рядом, когда тема пилота будет выбрана.

@register("предпосылки")
def _prerequisites(context: GeneratorContext) -> Variant:
    """
    «Назовите всё, на что опирается данная запись».

    Эталон --- запрос ``требует+``: транзитивное замыкание предпосылок.
    """
    v = context.vocabulary
    graph = context.graph
    # годятся единицы контента, у которых предпосылки вообще есть
    candidates = [
        node for node in content_units(context.content)
        if rpq_reachable(graph, node, f"{v.role_requires}+")
    ]
    target = context.pick(candidates, "запись с предпосылками")
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"Назовите всё, на что опирается «{target}» "
               f"(включая опосредованные предпосылки).",
        expectation=QueryExpectation(
            start=target,
            pattern=f"{v.role_requires}+",
            explanation=f"транзитивные предпосылки записи «{target}»",
        ),
        data={"запись": target},
    )


@register("прямые_предпосылки")
def _direct_prerequisites(context: GeneratorContext) -> Variant:
    """
    «Назовите непосредственные предпосылки» --- один шаг вместо замыкания.

    Отличается от :func:`_prerequisites` ровно паттерном, и это показательно:
    разница между «понял транзитивность» и «не понял» выражается сменой ``+``
    на один шаг.
    """
    v = context.vocabulary
    graph = context.graph
    candidates = [
        node for node in content_units(context.content)
        if rpq_reachable(graph, node, v.role_requires)
    ]
    target = context.pick(candidates, "запись с предпосылками")
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"Назовите непосредственные предпосылки «{target}» "
               f"(только те, на которые он опирается напрямую).",
        expectation=QueryExpectation(
            start=target,
            pattern=v.role_requires,
            explanation=f"прямые предпосылки записи «{target}»",
        ),
        data={"запись": target},
    )


@register("обоснования_доказательства")
def _proof_justifications(context: GeneratorContext) -> Variant:
    """
    «На что опирается доказательство этой теоремы».

    Эталон --- запрос через три связи: от теоремы к её доказательству, оттуда
    по композиции к шагам, и от шагов к обоснованиям.
    """
    v = context.vocabulary
    graph = context.graph
    candidates = [
        node for node in nodes(graph, f"@meta={v.proof}")
        if rpq_reachable(graph, node, f"comp {v.role_justified_by}")
    ]
    proof = context.pick(candidates, "доказательство с размеченными шагами")
    theses = sorted(rpq_reachable(graph, proof, v.role_proves))
    thesis = theses[0] if theses else proof
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"На какие утверждения и понятия опираются шаги доказательства "
               f"«{thesis}»?",
        expectation=QueryExpectation(
            start=proof,
            pattern=f"comp {v.role_justified_by}",
            explanation=f"обоснования шагов доказательства «{proof}»",
        ),
        data={"доказательство": proof, "тезис": thesis},
    )


@register("вид_записи")
def _classify_record(context: GeneratorContext) -> Variant:
    """
    «Какого вида эта запись» --- понятие, определение, теорема, …

    Эталон --- узловой атом ``instanceOf``: вид записи не хранится отдельно,
    он и есть её класс в онтологии.
    """
    target = context.pick(content_units(context.content), "единица контента")
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"К какому виду единиц контента относится «{target}»?",
        expectation=QueryExpectation(
            start=target,
            pattern="instanceOf",
            explanation=f"класс онтологии, экземпляром которого является «{target}»",
        ),
        data={"запись": target},
        answer_kind="множество",
    )


@register("нарисуй_иерархию")
def _draw_hierarchy(context: GeneratorContext) -> Variant:
    """
    «Нарисуйте диаграмму»: иерархия вида записи и её предпосылки.

    Эталон --- подграф онтологии, вычисленный запросом. Ответ придёт в виде
    SVG, разберётся обратно в модель и сравнится с этим подграфом.
    """
    v = context.vocabulary
    graph = context.graph
    candidates = [
        node for node in content_units(context.content)
        if rpq_reachable(graph, node, f"{v.role_requires}+")
    ]
    target = context.pick(candidates, "запись с предпосылками")
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"Нарисуйте диаграмму классов ONTOL: запись «{target}», все её "
               f"предпосылки и связи «{v.role_requires}» между ними.",
        expectation=SubgraphExpectation(
            start=target,
            scope=f"{v.role_requires}*",
            labels=(v.role_requires,),
            explanation=f"фрагмент онтологии вокруг «{target}» по связи "
                        f"«{v.role_requires}»",
        ),
        data={"запись": target},
        answer_kind="диаграмма",
    )


@register("мощность_объединения")
def _union_size(context: GeneratorContext) -> Variant:
    """
    «Сколько элементов в объединении двух множеств» --- образец задачи с данными.

    Показывает второй случай: данные порождены генератором, и эталон ---
    ЧИСЛО, которое запросом к онтологии не выражается. Обоснование обязательно
    и уходит в ``reason``.
    """
    rng = context.rng
    left = sorted(rng.sample(range(1, 30), rng.randint(3, 6)))
    right = sorted(rng.sample(range(1, 30), rng.randint(3, 6)))
    return Variant(
        task_code=context.task_code,
        seed=context.seed,
        prompt=f"Даны множества A = {set(left)} и B = {set(right)}. "
               f"Сколько элементов в A ∪ B?",
        expectation=ValueExpectation(
            value=len(set(left) | set(right)),
            reason="ответ --- число, вычисляемое по данным варианта; язык "
                   "запросов к онтологии не содержит арифметики и считает "
                   "достижимость, а не значения (§6.3 docs/internal/"
                   "discrete-ontology.md)",
            explanation="мощность объединения двух множеств",
        ),
        data={"A": left, "B": right},
        answer_kind="число",
    )


# ПОРОЖДЕНИЕ ВАРИАНТА

def task_node(content: Content, task_code: str) -> str:
    """
    Найти узел задачи по её коду.

    Поиск идёт по слотам, а не запросом-паттерном, намеренно: это служебная
    операция, а не проверка ответа студента, и она должна работать даже если
    код записан так, что узловым атомом не адресуется. За адресуемость кодов
    отвечает отдельный инвариант загрузчика («код адресуем запросом»).

    :param content: загруженный контент
    :param task_code: код задачи

    :return: имя узла-задачи

    :raises VariantError: задача не найдена либо код неоднозначен
    """
    v = content.vocabulary
    tasks = content.instances_of(v.task)
    matched = sorted(
        node for node in tasks
        if str(content.graph.slot(node, v.slot_code) or "") == task_code
    )
    if not matched:
        raise VariantError(
            f"В контенте нет задачи с кодом {task_code!r} "
            f"(известны: {', '.join(sorted(tasks)) or 'ни одной'})"
        )
    if len(matched) > 1:
        raise VariantError(
            f"Код задачи {task_code!r} неоднозначен: {', '.join(matched)}"
        )
    return matched[0]


def generator_name(content: Content, task_code: str) -> str:
    """
    Имя генератора, указанное у задачи в онтологии.

    :param content: загруженный контент
    :param task_code: код задачи

    :return: значение слота ``генератор``

    :raises VariantError: задача не найдена либо генератор не указан
    """
    node = task_node(content, task_code)
    name = content.graph.slot(node, content.vocabulary.slot_generator)
    if not name:
        raise VariantError(
            f"У задачи {node!r} (код {task_code!r}) не указан слот "
            f"«{content.vocabulary.slot_generator}»"
        )
    return str(name)


def generate(content: Content, task_code: str, seed: int,
             vocabulary: Optional[Vocabulary] = None) -> Variant:
    """
    Породить вариант задачи по коду и сиду.

    Детерминированно: одна и та же пара «код + сид» всегда даёт один и тот же
    вариант. Поэтому журналу достаточно хранить сид, а не задание целиком.

    :param content: загруженный контент
    :param task_code: код задачи в контенте
    :param seed: сид варианта
    :param vocabulary: словарь имён (по умолчанию --- из контента)

    :return: вариант задания

    :raises VariantError: задача не найдена, генератор не указан или не
        зарегистрирован, либо генератор вернул не вариант
    """
    name = generator_name(content, task_code)
    function = REGISTRY.get(name)
    if function is None:
        known = ", ".join(sorted(REGISTRY)) or "ни одного"
        raise VariantError(
            f"Генератор {name!r} не зарегистрирован (известны: {known})"
        )

    context = GeneratorContext(
        task_code=task_code,
        seed=seed,
        # Сид строкой из кода и числа: один и тот же номер варианта в разных
        # задачах даёт разные данные, а не синхронно повторяющиеся.
        rng=random.Random(f"{task_code}|{seed}"),
        content=content,
        vocabulary=vocabulary or content.vocabulary,
    )
    variant = function(context)
    if not isinstance(variant, Variant):
        raise VariantError(
            f"Генератор {name!r} вернул {type(variant).__name__}, ожидался Variant"
        )
    return variant


def generate_many(content: Content, task_code: str,
                  seeds: Sequence[int]) -> Tuple[Variant, ...]:
    """
    Породить несколько вариантов одной задачи --- по варианту на сид.

    :param content: загруженный контент
    :param task_code: код задачи
    :param seeds: сиды вариантов

    :return: кортеж вариантов в порядке сидов
    """
    return tuple(generate(content, task_code, seed) for seed in seeds)
