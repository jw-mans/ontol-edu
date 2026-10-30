"""
Схема онтологии дискретной математики как диаграмма классов ONTOL.

Схема строится в одном из трёх профилей, которые определяют единицей контента,
работающих как переключатели слоёв:

- :attr:`Profile.FULL` --- единица контента это абстрактный класс
  «ЕдиницаКонтента», конкретизируемый понятием, определением, утверждением и
  доказательством; задачи --- отдельный слой;
- :attr:`Profile.CONCEPTS` --- единица контента это понятие, а определения и
  формулировки лежат текстом в его слотах;
- :attr:`Profile.TASKS` --- карты знаний нет, есть только задачи с вариантами.

Профили НЕ независимы, и это сделано намеренно. ``FULL`` --- надмножество: два
других получаются из него отбрасыванием слоёв. Поэтому контент наполняется один
раз в полном профиле, а переключение профиля меняет схему и запросы, не требуя
переписывать данные. Обратное (наполнить в ``CONCEPTS`` и перейти к ``FULL``)
невозможно без ручной работы: свёрнутое в текст содержание уже не восстановить
как отдельные узлы графа.

Все имена берутся из :mod:`discrete.names`; строковых литералов с именами
классов, ролей и слотов в этом модуле нет.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from uml_dsl.diagram import ClassDiagram
from uml_dsl.enums import AggregationKind, Stereotype
from uml_dsl.models import Attribute, Class
from uml_dsl.relationships import Association, AssociationEnd

from .names import VOCABULARY, Vocabulary


class Profile(str, Enum):
    """Вариант схемы: что считается единицей контента."""

    #: Абстрактная единица контента + подвиды, задачи отдельным слоем.
    FULL = "полный"
    #: Единица контента --- понятие; остальное содержание текстом в слотах.
    CONCEPTS = "понятия"
    #: Только задачи и варианты, карта знаний не строится.
    TASKS = "задачи"


def _slots(*names: str) -> List[Attribute]:
    """
    Создать список атрибутов-слотов по именам.

    :param names: имена слотов

    :return: список атрибутов без начальных значений
    """
    return [Attribute(name=name) for name in names]


def _association(source: Class, target: Class, role: str,
                 name: Optional[str] = None) -> Association:
    """
    Ассоциация с ролью на ВТОРОМ полюсе --- так роль становится меткой ребра.

    Направление ребра в графе: ``source -> target`` (``ends[0] -> ends[1]``),
    роль читается только с ``ends[1]``.

    :param source: классификатор-клиент (кто ссылается)
    :param target: классификатор-поставщик (на кого ссылаются)
    :param role: роль второго полюса, она же метка ребра в запросах
    :param name: необязательное имя ассоциации

    :return: ассоциация, готовая к добавлению в диаграмму
    """
    return Association(
        name=name,
        ends=[
            AssociationEnd(participant=source, aggregation=AggregationKind.NONE),
            AssociationEnd(participant=target, role=role,
                           aggregation=AggregationKind.NONE),
        ],
    )


def build_schema(profile: Profile = Profile.FULL,
                 vocabulary: Vocabulary = VOCABULARY) -> ClassDiagram:
    """
    Собрать схему онтологии в заданном профиле.

    :param profile: вариант схемы (см. :class:`Profile`)
    :param vocabulary: словарь имён (по умолчанию кириллический)

    :return: диаграмма классов --- вход для :func:`ontol.query.diagram_to_graph`

    :raises ValueError: словарь имён некорректен
    """
    vocabulary.validate()
    v = vocabulary
    diagram = ClassDiagram(title=f"Онтология дискретной математики ({profile.value})")

    classes: Dict[str, Class] = {}

    def add(name: str, *, abstract: bool = False,
            stereotype: Optional[Stereotype] = None,
            slots: Optional[List[Attribute]] = None) -> Class:
        """Создать класс, положить в диаграмму и запомнить по имени."""
        cls = Class(name=name, is_abstract=abstract, stereotype=stereotype,
                    attributes=slots or [])
        classes[name] = cls
        diagram.add_classifier(cls)
        return cls

    def compose(whole: Class, part: Class) -> None:
        """Композиция «целое -> часть» (метка ребра ``comp``)."""
        diagram.add_aggregation(whole, part,
                                aggregation_kind=AggregationKind.COMPOSITION)

    # организация курса: есть во всех профилях
    course = add(v.course, slots=_slots(v.slot_term))
    topic = add(v.topic, slots=_slots(v.slot_number))
    compose(course, topic)

    # словари уровней и видов ответа: есть во всех профилях
    add(v.difficulty_level, stereotype=Stereotype.ENUMERATION)
    add(v.answer_kind, stereotype=Stereotype.ENUMERATION)

    # слой задач: есть во всех профилях
    task = add(v.task, slots=_slots(
        v.slot_level, v.slot_kind, v.slot_generator, v.slot_text))
    variant = add(v.variant, slots=_slots(v.slot_seed, v.slot_expected))
    compose(task, variant)

    if profile is Profile.TASKS:
        # Карты знаний нет: тема состоит прямо из задач, ссылаться не на что.
        compose(topic, task)
        return diagram

    # содержательный слой
    if profile is Profile.FULL:
        # Единица контента --- абстрактный класс с подвидами.
        reference_target = add(
            v.unit, abstract=True,
            slots=_slots(v.slot_code, v.slot_level, v.slot_text))
        concept = add(v.concept)
        definition = add(v.definition, slots=_slots(v.slot_kind))
        statement = add(v.statement, abstract=True)
        proof = add(v.proof, slots=_slots(v.slot_method))
        proof_step = add(v.proof_step, slots=_slots(v.slot_number, v.slot_text))
        theorem = add(v.theorem)
        lemma = add(v.lemma)

        for child in (concept, definition, statement, proof):
            diagram.add_generalization(child, reference_target)
        for child in (theorem, lemma):
            diagram.add_generalization(child, statement)

        # Определение определяет понятие.
        diagram.add_association(_association(definition, concept, v.role_defines))

        # Доказательства по шагам --- слой размечается.
        compose(proof, proof_step)
        diagram.add_association(_association(proof, statement, v.role_proves))
        diagram.add_association(
            _association(proof_step, reference_target, v.role_justified_by))
        diagram.add_association(_association(proof_step, proof_step, v.role_next))
    else:
        # Профиль CONCEPTS: единица контента --- понятие, остальное в слотах.
        reference_target = add(v.concept, slots=_slots(
            v.slot_code, v.slot_level, v.slot_text,
            v.definition, v.statement, v.proof))

    # Общее для FULL и CONCEPTS: тема состоит из единиц контента,
    # единицы требуют друг друга, задачи их проверяют.
    compose(topic, reference_target)
    diagram.add_association(
        _association(reference_target, reference_target, v.role_requires))
    diagram.add_association(_association(task, reference_target, v.role_checks))
    return diagram


def reference_class(profile: Profile = Profile.FULL,
                    vocabulary: Vocabulary = VOCABULARY) -> str:
    """
    Имя класса, на который в данном профиле ссылаются ``требует``/``проверяет``.

    Нужно прикладному коду, чтобы один и тот же запрос работал во всех
    профилях: в ``FULL`` это «ЕдиницаКонтента», в ``CONCEPTS`` --- «Понятие»,
    а в ``TASKS`` ссылаться не на что.

    :param profile: вариант схемы
    :param vocabulary: словарь имён

    :return: имя класса-цели ссылок

    :raises ValueError: в профиле ``TASKS`` карты знаний нет
    """
    if profile is Profile.FULL:
        return vocabulary.unit
    if profile is Profile.CONCEPTS:
        return vocabulary.concept
    raise ValueError(
        f"В профиле {profile.value!r} карты знаний нет: ссылаться не на что"
    )
