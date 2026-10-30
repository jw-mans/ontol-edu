"""
Модели отношений UML: зависимость, обобщение, ассоциация‚
агрегация, композиция, класс ассоциации, набор обобщений.

Все поля и проверки подкреплены цитатами из книги «Моделирование на UML»
(Новиков, Иванов), раздел 3.3.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import (
    AggregationKind,
    Changeability,
    CollectionKind,
    DependencyStereotype,
    Stereotype,
    Visibility,
)
from .models import Attribute, Classifier, Class, MultiplicityRange


# ═══════════════════════════════════════════════════════════════════════════
# Relationship — базовый класс отношений (§3.14, рис. 3.14)
# ═══════════════════════════════════════════════════════════════════════════


# Note: removed `Relationship` abstract class as it contained no fields
# and subclasses can inherit directly from `BaseModel`.


# ═══════════════════════════════════════════════════════════════════════════
# Полюс ассоциации (Association End)
# ═══════════════════════════════════════════════════════════════════════════


def _participant_name(p: Any) -> str:
    """Имя участника полюса. Для Class — его имя; для отношения (association-to-
    relationship) — собственное имя связи или синтезированное из её концов.

    CIAO-расширение (напр. Рис.1): полюс ассоциации может ссылаться не только на
    классификатор, но и на другое отношение.
    """
    if isinstance(p, Class):
        return p.name
    nm = getattr(p, "name", None)
    if nm:
        return nm
    kind = type(p).__name__
    ends: List[str] = []
    if isinstance(p, Association):
        ends = [_participant_name(e.participant) for e in p.ends]
    elif isinstance(p, Generalization):
        ends = [p.specific.name, p.general.name]
    elif isinstance(p, Dependency):
        ends = [p.client.name, p.supplier.name]
    elif isinstance(p, Realization):
        ends = [p.implementer.name, p.interface_.name]
    return f"{kind}({', '.join(ends)})"


class AssociationEnd(BaseModel):
    """Полюс ассоциации (§3.3.3–§3.3.8).

    Цитата: «Связь (link) — это экземпляр ассоциации, который представляет
    собой упорядоченный набор (кортеж, tuple) ссылок на экземпляры
    классификаторов на полюсах ассоциации.»

    Цитата: «Роль (role) — это интерфейс, который предоставляет
    классификатор в данной ассоциации.»
    """
    participant: Union[Class, "Association", "Generalization", "Dependency", "Realization"] = Field(
        ...,
        description=(
            "Участник полюса: классификатор (Class) ИЛИ отношение "
            "(Association/Generalization/Dependency/Realization). Вариант с отношением — "
            "это «ассоциация к связи» (association-to-relationship), нужная для метамоделей "
            "(напр. CIAO Рис.1). Имя участника — через свойство `participant_name`."
        ),
    )

    @property
    def participant_name(self) -> str:
        """Имя участника полюса, безопасное и для классов, и для отношений."""
        return _participant_name(self.participant)

    role: Optional[str] = Field(
        default=None,
        description=(
            "Имя роли. "
            "Цитата: «Роль полюса ассоциации (association end role)— способ указать, "
            "как именно участвует классификатор в ассоциации.»"
        ),
    )
    multiplicity: Optional[MultiplicityRange] = Field(
        default=None,
        description=(
            "Кратность полюса. "
            "Цитата: «Кратность полюса указывает, сколько объектов на этом конце "
            "участвуют в связи.»"
        ),
    )
    navigable: Optional[bool] = Field(
        default=None,
        description=(
            "Возможность навигации. "
            "Цитата: «Возможность навигации (navigability) для полюса ассоциации — "
            "свойство полюса, имеющее значение типа Boolean, определяющее, можно ли "
            "эффективно получить доступ к объектам класса.» "
            "Стрелка → = navigable, X = not navigable, отсутствие = не определено."
        ),
    )
    role_visibility: Optional[Visibility] = Field(
        default=None,
        description=(
            "Видимость полюса ассоциации. "
            "Цитата: «Видимость полюса ассоциации — указание того, является ли "
            "классификатор видимым для классификаторов, маршруты из которых ведут к нему.»"
        ),
    )
    aggregation: AggregationKind = Field(
        default=AggregationKind.NONE,
        description=(
            "Вид агрегации на этом полюсе (none / aggregation / composition). "
            "Цитата-агрегация: «Агрегация — пустой ромб.» "
            "Цитата-композиция: «Композиция — закрашенный ромб.»"
        ),
    )
    is_derived: bool = Field(
        default=False,
        description=(
            "Производная роль (/ перед именем). "
            "Цитата: «Производный элемент — это элемент, который можно вычислить.»"
        ),
    )
    collection_kind: CollectionKind = Field(
        default=CollectionKind.SET,
        description=(
            "Упорядоченность и уникальность. По умолчанию {set}. "
            "Цитата: «{ordered} — упорядоченное множество без повторов.»"
        ),
    )
    changeability: Optional[Changeability] = Field(
        default=None,
        description=(
            "Изменяемость множества объектов на полюсе. "
            "Цитата: «То же самое свойство {readOnly} можно применить к полюсу ассоциации.»"
        ),
    )
    qualifiers: List[Attribute] = Field(
        default_factory=list,
        description=(
            "Квалификаторы полюса (§3.3.8). "
            "Цитата: «Квалификатор полюса ассоциации (qualifier) — атрибут полюса "
            "ассоциации, значение которого позволяет выделить объекты на другом полюсе.»"
        ),
    )
    subsets: Optional[AssociationEnd] = Field(
        default=None,
        description=(
            "{subsets x} — ссылка на полюс ассоциации (AssociationEnd) x, множество объектов является его подмножеством. "
            "Значение должно ссылаться на существующий полюс той же ассоциации (по роли или участнику)."
        ),
    )
    is_union: bool = Field(
        default=False,
        description=(
            "{union} — множество является объединением всех субмножеств. "
            "Цитата: «Ограничение {union} — указание на то, что множество объектов "
            "есть объединение всех подмножеств.»"
        ),
    )
    redefines: Optional[str] = Field(
        default=None,
        description="Переопределяемая роль (redefines).",
    )
    role_type: Optional[Class] = Field(
        default=None,
        description=(
            "Тип роли — ссылка на `Class`, определяющий тип ролевого участия на этом полюсе.",
        ),
    )


class AggregationEnd(AssociationEnd):
    """Специализованный полюс ассоциации для агрегации/композиции.

    Проверяет, что поле `aggregation` имеет значение AGGREGATION или COMPOSITION.
    """
    @model_validator(mode="after")
    def _must_be_aggregation_or_composition(self) -> "AggregationEnd":
        if self.aggregation not in (AggregationKind.AGGREGATION, AggregationKind.COMPOSITION):
            raise ValueError("AggregationEnd must have aggregation=AGGREGATION or COMPOSITION")
        return self


# ═══════════════════════════════════════════════════════════════════════════
# Зависимость (Dependency)
# ═══════════════════════════════════════════════════════════════════════════


class Dependency(BaseModel):
    """Отношение зависимости (§3.3.1).

    Поля `client` и `supplier` содержат объекты `Class` (реализующий и
    независимый классификатор соответственно)."""
    client: Class = Field(
        ..., description="Зависимый элемент (реализующий классификатор).",
    )
    supplier: Class = Field(
        ..., description="Независимый элемент (класс/интерфейс).",
    )
    stereotype: Optional[DependencyStereotype] = Field(
        default=None,
        description="Стереотип зависимости (bind, call, use и т.д.)",
    )

    @model_validator(mode="after")
    def _no_self_dependency(self) -> "Dependency":
        if self.client.name == self.supplier.name:
            raise ValueError("Зависимость не может быть на самого себя")
        return self


# ═══════════════════════════════════════════════════════════════════════════
# Реализация (Realization)
# ═══════════════════════════════════════════════════════════════════════════


class Realization(BaseModel):
    """Отношение реализации (§3.3.1).

    Показывает, что `client` (класс) реализует `supplier` (интерфейс).
    Поля хранят ссылки на объекты `Classifier`.
    """
    implementer: Class = Field(
        ..., description="Реализующий классификатор (класс).",
    )
    interface_: Class = Field(
        ..., description="Реализуемый интерфейс (Class с stereotype=interface).",
    )

    @model_validator(mode="after")
    def _no_self_realization(self) -> "Realization":
        if self.implementer.name == self.interface_.name:
            raise ValueError("Реализация не может ссылаться на саму себя")
        return self

    @model_validator(mode="after")
    def _target_must_be_interface(self) -> "Realization":
        if getattr(self.interface_, "stereotype", None) != Stereotype.INTERFACE:
            raise ValueError(
                f"Реализация '{self.implementer.name} -> {self.interface_.name}' должна ссылаться на интерфейс"
            )
        return self

    @property
    def implementing_classifier(self) -> str:
        return self.implementer.name

    @property
    def interface(self) -> str:
        return self.interface_.name





# ═══════════════════════════════════════════════════════════════════════════
# Обобщение (Generalization)
# ═══════════════════════════════════════════════════════════════════════════


class Generalization(BaseModel):
    """Отношение обобщения (§3.3.2). Наследует Relationship (§3.14, рис. 3.14).

    Цитата: «Принцип подстановки, сформулированный Барбарой Лисков (Liskov
    substitution principle) заключается в том, что экземпляр подкласса
    может использоваться везде, где используется экземпляр суперкласса.»

    Цитата: «Обобщения в модели должны образовывать строгий частичный порядок.»
    (т.е. циклы наследования запрещены)

    Нотация: стрелка с большим незакрашенным треугольным наконечником
    от подкласса к суперклассу.
    """
    specific: Classifier = Field(
        ..., description="Конкретный классификатор (подкласс).",
    )
    general: Classifier = Field(
        ..., description="Обобщающий классификатор (суперкласс).",
    )
    is_substitutable: bool = Field(
        default=True,
        description=(
            "По умолчанию обобщения подчиняются принципу подстановки. "
            "Цитата: «По умолчанию обобщения являются подстановочными (isSubstitutable).»"
        ),
    )

    @model_validator(mode="after")
    def _no_self_generalization(self) -> "Generalization":
        """Цитата: «Обобщения должны образовывать строгий частичный порядок»
        → рефлексивность запрещена.
        """
        if self.specific.name == self.general.name:
            raise ValueError(
                f"Классификатор '{self.specific.name}' не может быть обобщением самого себя"
            )
        return self


# ═══════════════════════════════════════════════════════════════════════════
# Набор обобщений (GeneralizationSet)
# ═══════════════════════════════════════════════════════════════════════════


class GeneralizationSet(BaseModel):
    """Набор обобщений с ограничениями complete/disjoint (§3.3.2).

    Цитата: «{complete} — все возможные подтипы определены; каждый экземпляр
    суперкласса должен быть экземпляром какого-либо подкласса.
    {incomplete} — определены лишь некоторые подтипы.
    {disjoint} — подклассы взаимно исключают друг друга.
    {overlapping} — подклассы могут пересекаться.»

    Цитата: «Значения ограничений по умолчанию — {incomplete, disjoint}.»
    """
    name: Class = Field(
        ...,
        description="Имя набора обобщений (ссылка на Class, показывающий суперкласс/контекст).",
    )
    generalizations: List[Generalization] = Field(
        default_factory=list,
        description="Обобщения, входящие в этот набор.",
    )
    is_complete: bool = Field(
        default=False,
        description=(
            "{complete} — все подтипы определены. По умолчанию False ({incomplete}). "
            "Цитата: «{complete} и {incomplete} взаимно исключают друг друга.»"
        ),
    )
    is_disjoint: bool = Field(
        default=True,
        description=(
            "{disjoint} — подклассы взаимно исключают друг друга. По умолчанию True. "
            "Цитата: «{disjoint} и {overlapping} взаимно исключают друг друга.»"
        ),
    )

    def constraint_label(self) -> str:
        """Формирует текстовую метку ограничений для SVG."""
        parts: list[str] = []
        parts.append("complete" if self.is_complete else "incomplete")
        parts.append("disjoint" if self.is_disjoint else "overlapping")
        return "{" + ", ".join(parts) + "}"


# ═══════════════════════════════════════════════════════════════════════════
# Ассоциация (Association)
# ═══════════════════════════════════════════════════════════════════════════


class Association(BaseModel):
    """Ассоциация между классификаторами (§3.3.3–§3.3.8).

    Цитата: «Ассоциация означает, что экземпляры одного класса связаны
    с экземплярами другого класса.»

    Цитата: «Ассоциация — это классификатор, экземплярами которого
    являются связи (links).»

    Нотация: сплошная линия между классами.
    """
    name: Optional[str] = Field(
        default=None,
        description=(
            "Имя ассоциации. "
            "Цитата: «Имя ассоциации — текстовая строка рядом с линией ассоциации.»"
        ),
    )
    ends: List[AssociationEnd] = Field(
        ..., min_length=2,
        description=(
            "Полюса ассоциации (минимум 2). "
            "Цитата (бинарная): «Связь — упорядоченный набор ссылок (кортеж).»"
        ),
    )
    is_derived: bool = Field(
        default=False,
        description=(
            "Производная ассоциация. "
            "Цитата: «Производный элемент — элемент, который можно вычислить.»"
        ),
    )

    @model_validator(mode="after")
    def _at_least_two_ends(self) -> "Association":
        """Цитата: «Ассоциация должна связывать как минимум два классификатора.»"""
        if len(self.ends) < 2:
            raise ValueError("Ассоциация должна иметь минимум 2 полюса")
        return self

    @model_validator(mode="after")
    def _composition_at_most_one(self) -> "Association":
        """Цитата: «Композиционно часть A может входить только в одно целое B.»
        → Максимум один полюс может быть composition.
        """
        comp_count = sum(
            1 for e in self.ends if e.aggregation == AggregationKind.COMPOSITION
        )
        if comp_count > 1:
            raise ValueError(
                "В ассоциации не может быть более одного полюса с композицией"
            )
        return self

    @model_validator(mode="after")
    def _aggregation_at_most_one(self) -> "Association":
        """Максимум один полюс может быть агрегацией/композицией (сторона «целого»)."""
        agg_count = sum(
            1
            for e in self.ends
            if e.aggregation in (AggregationKind.AGGREGATION, AggregationKind.COMPOSITION)
        )
        if agg_count > 1:
            raise ValueError(
                "В ассоциации не может быть более одного полюса с агрегацией/композицией"
            )
        return self

    @model_validator(mode="after")
    def _aggregation_composition_binary_rule(self) -> "Association":
        """Если хотя бы один полюс является агрегацией/композицией, ассоциация
        должна быть бинарной и иметь ровно один такой полюс.
        """
        agg_ends = [
            e for e in self.ends if e.aggregation in (AggregationKind.AGGREGATION, AggregationKind.COMPOSITION)
        ]
        if agg_ends:
            if len(self.ends) != 2:
                raise ValueError(
                    "Ассоциация с агрегацией/композицией должна быть бинарной (иметь ровно 2 полюса)"
                )
            if len(agg_ends) != 1:
                raise ValueError(
                    "Ассоциация с агрегацией/композицией должна иметь ровно один полюс вида aggregation/composition"
                )
        return self

    @model_validator(mode="after")
    def _subsets_refer_to_existing_end(self) -> "Association":
        """Ensure that if an end.subsets is set, it refers to an end that
        exists in the same association (by role name or participant name).
        """
        # collect role names and participant names of ends in this association
        role_names = {e.role for e in self.ends if e.role}
        participant_names = {_participant_name(e.participant) for e in self.ends}
        for e in self.ends:
            if getattr(e, "subsets", None) is None:
                continue
            target = e.subsets
            # If target is an AssociationEnd instance, check by its role or participant
            if isinstance(target, AssociationEnd):
                t_role = getattr(target, "role", None)
                t_part = _participant_name(target.participant) if getattr(target, "participant", None) else None
                if (t_role and t_role in role_names) or (t_part and t_part in participant_names):
                    continue
                raise ValueError(
                    f"Поле 'subsets' у полюса ссылается на полюс, не присутствующий в той же ассоциации: '{t_role or t_part}'"
                )
            else:
                raise ValueError("Поле 'subsets' должно ссылаться на AssociationEnd")
        return self

    def is_binary(self) -> bool:
        return len(self.ends) == 2

    def is_nary(self) -> bool:
        """Цитата: «Многополюсная ассоциация — с формальной точки зрения излишняя,
        поскольку её можно выразить через бинарные ассоциации, но практически
        незаменимая в определённых случаях.»
        """
        return len(self.ends) > 2


# ═══════════════════════════════════════════════════════════════════════════
# Класс ассоциации (Association Class)
# ═══════════════════════════════════════════════════════════════════════════


class AssociationClass(Association):
    """Класс ассоциации (§3.3.8).

    Цитата: «Класс ассоциации (association class) — сущность, которая является
    ассоциацией, но также имеет в своём составе составляющие класса.»

    Цитата: «Класс ассоциации не может иметь двух одинаковых кортежей.»

    Нотация: символ класса, соединённый пунктирной линией с линией ассоциации.
    """
    associated_classifier: Class = Field(
        ...,
        description="Ссылка на связанный класс (содержит атрибуты/операции).",
    )


class TemplateBinding(BaseModel):
    """Подстановка параметров шаблона.

    Связывает конкретный bound element с шаблоном и хранит фактические
    значения параметров, например `T = User`.
    """
    bound_element: Class = Field(..., description="Классификатор, использующий шаблон.")
    template: Class = Field(..., description="Шаблонный классификатор.")
    substitutions: Dict[str, str] = Field(
        default_factory=dict,
        description="Подстановки формальных параметров шаблона.",
    )

    @model_validator(mode="after")
    def _must_have_substitutions(self) -> "TemplateBinding":
        if not self.substitutions:
            raise ValueError("Подстановка шаблона должна содержать хотя бы один параметр")
        return self


# CIAO-расширение: разрешаем forward-ссылки в AssociationEnd.participant
# (Association/Generalization/Dependency/Realization определены ниже AssociationEnd) —
# нужно для association-to-relationship.
AssociationEnd.model_rebuild()
AggregationEnd.model_rebuild()
