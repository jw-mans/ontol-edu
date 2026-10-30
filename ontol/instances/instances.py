"""
Синтаксический сахар: объявление экземпляров классов ONTOL-онтологии.

Задача: конкретные данные должны не просто рисоваться отдельной картинкой, а
**продолжать диаграмму онтологии** --- её элементы суть экземпляры классов
онтологии:

1) класс ``Graph`` --- экземпляр метакласса ``Concept``;
2) определение ``acyclic`` --- экземпляр ``Definition``;
и т.д.

Связь «экземпляр--класс» рисуется штатной зависимостью UML со стереотипом
«instanceOf».

Писать такие коробки и связи руками многословно, поэтому здесь обёртка:

    d = InstanceDiagram("Экземпляры онтологии")
    concept = d.instance(meta_concept, "Graph")
    defn    = d.instance(meta_definition, "acyclic")
    d.compose(concept, defn)      # у понятия Graph есть определение acyclic
    diagram = d.build()           # готовая ClassDiagram (продолжает онтологию)

Классы онтологии (объекты ``uml_dsl.models.Class``) переиспользуются как есть.
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

from uml_dsl.diagram import ClassDiagram
from uml_dsl.enums import AggregationKind, DependencyStereotype
from uml_dsl.models import Attribute, Class
from uml_dsl.relationships import (
    AggregationEnd,
    Association,
    AssociationEnd,
    Dependency,
)

Slots = Mapping[str, object]


def instance_of(
    metaclass: Class, name: str, slots: Optional[Slots] = None,
    qualified: bool = True,
) -> Tuple[Class, Dependency]:
    """
    Объявить экземпляр метакласса: коробка со слотами + связь «instanceOf».

    Возвращает пару (коробка-экземпляр, зависимость «instanceOf» к метаклассу).

    Имя коробки --- в нотации UML ``имя : Метакласс`` (``qualified=True``) либо
    просто ``имя`` (``qualified=False``). Второй вариант нужен, когда диаграмма
    должна быть записываема в TDL: лексер TDL не принимает двоеточие в
    идентификаторе, и ``КЛАСС Graph : Concept`` даёт ``ParseError``. Потери
    смысла нет --- принадлежность классу на диаграмме и так показывает
    пунктирная связь «instanceOf», а запросам доступен атом ``@meta=Метакласс``.

    :param metaclass: класс онтологии, экземпляр которого объявляется
    :param name: имя экземпляра (понятия/определения/задачи/…)
    :param slots: значения слотов (атрибутов) экземпляра
    :param qualified: писать имя как ``имя : Метакласс`` (иначе только ``имя``)

    :return: пара (коробка-экземпляр, зависимость «instanceOf»)
    """
    box = Class(name=f"{name} : {metaclass.name}" if qualified else name, attributes=[
        Attribute(name=str(k), initial_value=v) for k, v in (slots or {}).items()
    ])
    dep = Dependency(
        client=box, supplier=metaclass, stereotype=DependencyStereotype.INSTANCE_OF,
    )
    return box, dep


class InstanceDiagram:
    """
    Построитель диаграммы, продолжающей онтологию экземплярами.

    Каждый ``instance`` добавляет коробку-экземпляр и связь «instanceOf» к
    классу-метаклассу; сами метаклассы (переиспользованные из онтологии) тоже
    попадают на диаграмму, чтобы связь имела оба конца.

    ``qualified=False`` переводит построитель в режим, пригодный для записи
    диаграммы в TDL: имена коробок --- одиночные идентификаторы без ``: Класс``
    (см. :func:`instance_of`). Для хранения экземпляров в TDL это обязательно.
    """

    def __init__(self, title: str, qualified: bool = True) -> None:
        """
        :param title: заголовок диаграммы
        :param qualified: имена коробок в нотации ``имя : Метакласс``;
            ``False`` --- только ``имя``, чтобы диаграмма записывалась в TDL
        """
        self.diagram = ClassDiagram(title=title)
        self.qualified = qualified
        self._metaclasses: Dict[str, Class] = {}

    def instance(self, metaclass: Class, name: str, **slots: object) -> Class:
        """Объявить экземпляр класса онтологии и вернуть его коробку."""
        box, dep = instance_of(metaclass, name, slots, qualified=self.qualified)
        if metaclass.name not in self._metaclasses:
            self._metaclasses[metaclass.name] = metaclass
            self.diagram.add_classifier(metaclass)
        self.diagram.add_classifier(box)
        self.diagram.dependencies.append(dep)
        return box

    def compose(self, whole: Class, part: Class, name: Optional[str] = None) -> None:
        """Композиция между экземплярами (экземпляр композиции онтологии)."""
        self.diagram.associations.append(Association(
            ends=[
                AggregationEnd(participant=whole, aggregation=AggregationKind.COMPOSITION),
                AssociationEnd(participant=part, aggregation=AggregationKind.NONE),
            ],
            name=name,
        ))

    def link(self, a: Class, b: Class, role: Optional[str] = None,
             stereotype: Optional[DependencyStereotype] = None) -> None:
        """Ассоциация/зависимость между экземплярами (ссылка одного на другой)."""
        if stereotype is not None:
            self.diagram.dependencies.append(
                Dependency(client=a, supplier=b, stereotype=stereotype))
        else:
            self.diagram.associations.append(Association(ends=[
                AssociationEnd(participant=a, aggregation=AggregationKind.NONE),
                AssociationEnd(participant=b, role=role, aggregation=AggregationKind.NONE),
            ]))

    def build(self) -> ClassDiagram:
        """Готовая диаграмма (классы онтологии + экземпляры + связи «instanceOf»)."""
        return self.diagram

# рендер диаграммы классов в DOT (для PNG через Graphviz)

def _rec_escape(text: str) -> str:
    for ch in ("\\", "{", "}", "|", "<", ">", '"'):
        text = text.replace(ch, "\\" + ch)
    return text


def instance_diagram_to_dot(diagram: ClassDiagram, name: str = "Instances") -> str:
    """
    Диаграмма классов -> DOT: 
    - записи с атрибутами, 
    - «instanceOf» пунктиром,
    - композиции ромбом. 
    Нужно для рендера в PNG (``dot -Tpng``), т.к. полный
    SVG-рендер ONTOL требует cairosvg для растеризации.
    """
    ids = {n: f"c{i}" for i, n in enumerate(diagram.classifiers)}
    lines = [
        f'digraph "{name}" {{',
        '  rankdir=TB; nodesep=0.5; ranksep=0.7;',
        '  node [shape=record, fontname="Arial", fontsize=10];',
        '  edge [fontname="Arial", fontsize=9];',
    ]
    for cname, cls in diagram.classifiers.items():
        attrs = getattr(cls, "attributes", []) or []
        head = _rec_escape(cname)
        stereo = getattr(cls, "stereotype", None)
        if stereo is not None: 
            head = "«" + _rec_escape(getattr(stereo, "value", str(stereo))) + "»\\n" + head
        if getattr(cls, "is_abstract", False):
            head = head + "\\n(abstract)"
        if attrs:
            body = "\\l".join(
                _rec_escape(f"{a.name} = {a.initial_value}" if a.initial_value is not None
                            else a.name)
                for a in attrs
            ) + "\\l"
            label = "{" + head + "|" + body + "}"
        else:
            label = head
        fill = ' style=filled fillcolor="#eef3fb"' if " : " in cname else ' style=filled fillcolor="#f3f3f3"'
        lines.append(f'  {ids[cname]} [label="{label}"{fill}];')

    # обобщения (наследование): полая треугольная стрелка specific -> general
    for gen in getattr(diagram, "generalizations", []):
        s, g = gen.specific.name, gen.general.name
        if s in ids and g in ids:
            lines.append(f'  {ids[s]} -> {ids[g]} [arrowhead=empty];')

    for dep in diagram.dependencies:
        if dep.client.name not in ids or dep.supplier.name not in ids:
            continue
        st = dep.stereotype.value if dep.stereotype else "depend"
        lines.append(
            f'  {ids[dep.client.name]} -> {ids[dep.supplier.name]} '
            f'[style=dashed, arrowhead=open, label="<<{st}>>"];'
        )
    for assoc in diagram.associations:
        if len(assoc.ends) != 2:
            continue
        a, b = assoc.ends[0], assoc.ends[1]
        na = getattr(a.participant, "name", None)
        nb = getattr(b.participant, "name", None)
        if na not in ids or nb not in ids:
            continue
        agg = getattr(a, "aggregation", None)
        if agg is not None and getattr(agg, "value", "") == "composition":
            lines.append(f'  {ids[na]} -> {ids[nb]} [dir=both, arrowtail=diamond, arrowhead=none];')
        else:
            role = getattr(b, "role", None)
            lbl = f' [arrowhead=vee, label="{role}"]' if role else ' [arrowhead=vee]'
            lines.append(f'  {ids[na]} -> {ids[nb]}{lbl};')
    lines.append("}")
    return "\n".join(lines)
