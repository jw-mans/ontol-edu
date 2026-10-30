"""
Class diagram model: classifiers, relationships, positions, and validation.
SVG rendering is delegated to the Graphviz-based renderer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, model_validator

from .enums import (
    AggregationKind,
)
from .models import (
    Class,
    Classifier,
    PRIMITIVE_TYPE_MAP,
)
from .relationships import (
    Association,
    AssociationClass,
    AssociationEnd,
    AggregationEnd,
    Dependency,
    Generalization,
    GeneralizationSet,
    Realization,
    TemplateBinding,
)


# ═══════════════════════════════════════════════════════════════════════════
# Позиция класса на диаграмме
# ═══════════════════════════════════════════════════════════════════════════


class ClassPosition(BaseModel):
    """Позиция и размер класса на диаграмме (для SVG рендеринга)."""
    classifier_name: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Диаграмма классов
# ═══════════════════════════════════════════════════════════════════════════


class ClassDiagram(BaseModel):
    """Контейнер всей модели диаграммы классов (§3.1–§3.3).

    Содержит классификаторы, отношение и глобальную валидацию.
    """
    title: str = Field(
        default="UML Class Diagram",
        description="Заголовок диаграммы.",
    )
    classifiers: Dict[str, Classifier] = Field(
        default_factory=dict,
        description="Словарь классификаторов (ключ — имя).",
    )
    associations: List[Association] = Field(
        default_factory=list,
        description="Ассоциации (бинарные, n-арные).",
    )
    association_classes: List[AssociationClass] = Field(
        default_factory=list,
        description="Классы ассоциаций (§3.3.8).",
    )
    generalizations: List[Generalization] = Field(
        default_factory=list,
        description="Обобщения.",
    )
    generalization_sets: List[GeneralizationSet] = Field(
        default_factory=list,
        description="Наборы обобщений.",
    )
    dependencies: List[Dependency] = Field(
        default_factory=list,
        description="Зависимости.",
    )
    realizations: List[Realization] = Field(
        default_factory=list,
        description="Реализации.",
    )
    template_bindings: List[TemplateBinding] = Field(
        default_factory=list,
        description="Подстановки параметров шаблонов (§3.2.5).",
    )

    # Позиции (заполняются при layout или пользовательском позиционировании)
    positions: Dict[str, ClassPosition] = Field(
        default_factory=dict,
        description="Позиции классификаторов на холсте.",
    )

    # True → рендер берёт positions как есть (пиксели, top-left = SVG-координаты)
    # и не раскладывает graphviz'ом. Используется для планарной раскладки.
    manual_layout: bool = Field(default=False)

    # ──── Удобные методы добавления ────────────────────────────────────

    def add_classifier(self, c: Classifier) -> "ClassDiagram":
        self.classifiers[c.name] = c
        return self

    def add_association(self, a: Association) -> "ClassDiagram":
        self.associations.append(a)
        return self

    def add_template_binding(self, binding: TemplateBinding) -> "ClassDiagram":
        self.template_bindings.append(binding)
        return self

    def add_association_class(self, a: AssociationClass) -> "ClassDiagram":
        self.association_classes.append(a)
        if a.associated_classifier.name not in self.classifiers:
            self.add_classifier(a.associated_classifier)
        return self

    def add_aggregation(
        self,
        whole: Any,
        part: Any,
        whole_multiplicity: Optional[MultiplicityRange] = None,
        part_multiplicity: Optional[MultiplicityRange] = None,
        name: Optional[str] = None,
        aggregation_kind: AggregationKind = AggregationKind.AGGREGATION,
        navigable_whole: Optional[bool] = None,
        navigable_part: Optional[bool] = None,
        **kw: Any,
    ) -> "ClassDiagram":
        """Convenience helper to add an aggregation/composition between two classifiers.

        `whole` and `part` may be either names (str) or `Classifier`/`Class` objects.
        The `whole` end will be created as `AggregationEnd` with the provided
        `aggregation_kind` (AGGREGATION or COMPOSITION). The `part` end will be
        a regular `AssociationEnd`.
        """
        # resolve participants to Classifier objects
        w_obj = whole
        p_obj = part
        if isinstance(whole, str):
            w_obj = self.classifiers.get(whole)
            if w_obj is None:
                raise ValueError(f"Unknown classifier '{whole}'")
        if isinstance(part, str):
            p_obj = self.classifiers.get(part)
            if p_obj is None:
                raise ValueError(f"Unknown classifier '{part}'")

        # Build ends
        w_end = AggregationEnd(
            participant=w_obj,
            aggregation=aggregation_kind,
            multiplicity=whole_multiplicity,
            navigable=navigable_whole,
        )
        p_end = AssociationEnd(
            participant=p_obj,
            multiplicity=part_multiplicity,
            navigable=navigable_part,
        )

        assoc = Association(name=name, ends=[w_end, p_end], **kw)
        self.associations.append(assoc)
        return self

    def add_generalization(
        self, specific: str, general: str, **kw: Any,
        ) -> "ClassDiagram":
        # Accept either names or Classifier objects. Resolve names to objects.
        s_obj = specific
        g_obj = general
        if isinstance(specific, str):
            s_obj = self.classifiers.get(specific)
            if s_obj is None:
                raise ValueError(f"Unknown classifier '{specific}'")
        if isinstance(general, str):
            g_obj = self.classifiers.get(general)
            if g_obj is None:
                raise ValueError(f"Unknown classifier '{general}'")
        self.generalizations.append(
            Generalization(specific=s_obj, general=g_obj, **kw)
        )
        return self

    def add_dependency(
        self, client: Any, supplier: Any, **kw: Any,
    ) -> "ClassDiagram":
        # Accept either names or Class objects. Resolve names to objects.
        c_obj = client
        s_obj = supplier
        if isinstance(client, str):
            c_obj = self.classifiers.get(client)
            if c_obj is None:
                raise ValueError(f"Unknown classifier '{client}'")
        if isinstance(supplier, str):
            s_obj = self.classifiers.get(supplier)
            if s_obj is None:
                raise ValueError(f"Unknown classifier '{supplier}'")
        self.dependencies.append(
            Dependency(client=c_obj, supplier=s_obj, **kw)
        )
        return self

    def add_realization(
        self, implementing: Any, interface: Any,
    ) -> "ClassDiagram":
        # Accept either names or Classifier objects. Resolve names to objects.
        impl_obj = implementing
        intf_obj = interface
        if isinstance(implementing, str):
            impl_obj = self.classifiers.get(implementing)
            if impl_obj is None:
                raise ValueError(f"Unknown classifier '{implementing}'")
        if isinstance(interface, str):
            intf_obj = self.classifiers.get(interface)
            if intf_obj is None:
                raise ValueError(f"Unknown classifier '{interface}'")
        self.realizations.append(
            Realization(implementer=impl_obj, interface_=intf_obj)
        )
        return self

    # ──── Глобальная валидация ──────────────────────────────────────────

    def validate_no_inheritance_cycles(self) -> None:
        """Цитата: «Обобщения в модели должны образовывать строгий частичный
        порядок.»  → циклы наследования = синтаксическая ошибка.
        """
        graph: Dict[str, List[str]] = {}
        for g in self.generalizations:
            graph.setdefault(g.specific.name, []).append(g.general.name)
        for gs in self.generalization_sets:
            for g in gs.generalizations:
                graph.setdefault(g.specific.name, []).append(g.general.name)

        visiting: Set[str] = set()
        visited: Set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise ValueError(
                    f"Обнаружен цикл наследования с участием '{node}'"
                )
            if node in visited:
                return
            visiting.add(node)
            for parent in graph.get(node, []):
                dfs(parent)
            visiting.discard(node)
            visited.add(node)

        for n in list(graph.keys()):
            dfs(n)

    def validate_composition_constraint(self) -> None:
        """Цитата: «Композиционно часть A может входить только в одно целое B,
        часть существует, только пока существует целое.»

        Проверяем, что классификатор не является «частью» в двух
        различных композициях.
        """
        parts_count: Dict[str, int] = {}
        for assoc in self.associations + self.association_classes:
            comp_ends = [
                e for e in assoc.ends
                if getattr(e, "aggregation", AggregationKind.NONE) == AggregationKind.COMPOSITION
            ]
            if not comp_ends:
                continue
            for end in assoc.ends:
                if getattr(end, "aggregation", AggregationKind.NONE) != AggregationKind.COMPOSITION:
                    parts_count[end.participant.name] = (
                        parts_count.get(end.participant.name, 0) + 1
                    )
        for part, count in parts_count.items():
            if count > 1:
                raise ValueError(
                    f"Класс '{part}' является частью в {count} композициях "
                    "(допускается максимум 1)"
                )

    def validate_multiple_inheritance_conflicts(self) -> None:
        """Цитата: «Конфликт при множественном наследовании возникает, если
        подкласс наследует атрибуты с одинаковыми именами, но разными типами
        от разных суперклассов.»
        """
        parents_map: Dict[str, List[str]] = {}
        for g in self.generalizations:
            parents_map.setdefault(g.specific.name, []).append(g.general.name)

        for child_name, parents in parents_map.items():
            if len(parents) < 2:
                continue
            inherited: Dict[str, List[Tuple[str, Optional[str]]]] = {}
            for p_name in parents:
                pcls = self.classifiers.get(p_name)
                if pcls:
                    for attr in pcls.attributes:
                        inherited.setdefault(attr.name, []).append(
                            (p_name, attr.type_)
                        )
            for attr_name, sources in inherited.items():
                if len(sources) > 1:
                    types = set(t for _, t in sources)
                    if len(types) > 1:
                        src_names = ", ".join(p for p, _ in sources)
                        raise ValueError(
                            f"Конфликт множественного наследования в '{child_name}': "
                            f"атрибут '{attr_name}' имеет разные типы от "
                            f"родителей {src_names}"
                        )

    def validate_all_ends_reference_known_classifiers(self) -> None:
        """Проверяем, что все полюса ассоциаций ссылаются на известные
        классификаторы."""
        known = set(self.classifiers.keys())
        for assoc in self.associations + self.association_classes:
            for end in assoc.ends:
                p = end.participant
                # CIAO-расширение: полюс может ссылаться на отношение
                # (association-to-relationship) — такие полюса не обязаны быть
                # классификаторами, пропускаем их.
                if not isinstance(p, Class):
                    continue
                if p.name not in known:
                    raise ValueError(
                        f"Полюс ассоциации ссылается на неизвестный "
                        f"классификатор '{p.name}'"
                    )

        for assoc_class in self.association_classes:
            if assoc_class.associated_classifier.name not in known:
                raise ValueError(
                    f"Класс ассоциации ссылается на неизвестный "
                    f"связанный классификатор '{assoc_class.associated_classifier.name}'"
                )

    def validate_all(self) -> None:
        """Выполнить все глобальные проверки."""
        self.validate_no_inheritance_cycles()
        self.validate_composition_constraint()
        self.validate_multiple_inheritance_conflicts()
        self.validate_redefines_references()
        self.validate_attribute_type_references()
        self.validate_parameter_type_references()
        self.validate_template_parameter_type_references()
        self.validate_template_binding_references()
        self.validate_all_ends_reference_known_classifiers()

    def validate_redefines_references(self) -> None:
        """Проверяем, что каждое `redefines` ссылается на реально существующее
        имя элемента (атрибута или операции) в родительских (ancestor) классификаторах.
        """
        # Build parent map
        parents_map: Dict[str, List[str]] = {}
        for g in self.generalizations:
            parents_map.setdefault(g.specific.name, []).append(g.general.name)
        for gs in self.generalization_sets:
            for g in gs.generalizations:
                parents_map.setdefault(g.specific.name, []).append(g.general.name)

        # helper to collect ancestors
        def collect_ancestors(name: str) -> Set[str]:
            res: Set[str] = set()
            stack = parents_map.get(name, [])[:]
            while stack:
                p = stack.pop()
                if p in res:
                    continue
                res.add(p)
                stack.extend(parents_map.get(p, []))
            return res

        for cls_name, cls in self.classifiers.items():
            ancestors = collect_ancestors(cls_name)
            if not ancestors:
                continue
            # collect names of members in ancestors
            anc_attrs: Set[str] = set()
            anc_ops: Set[str] = set()
            for a_name in ancestors:
                a_cls = self.classifiers.get(a_name)
                if not a_cls:
                    continue
                for attr in a_cls.attributes:
                    anc_attrs.add(attr.name)
                for op in a_cls.operations:
                    anc_ops.add(op.name)

            # check attributes
            for attr in cls.attributes:
                if getattr(attr, "redefines", None):
                    if attr.redefines not in anc_attrs:
                        raise ValueError(
                            f"Класс '{cls_name}': атрибут '{attr.name}' переопределяет несуществующий элемент '{attr.redefines}' в родителях"
                        )
            # check operations
            for op in cls.operations:
                if getattr(op, "redefines", None):
                    if op.redefines not in anc_ops:
                        raise ValueError(
                            f"Класс '{cls_name}': операция '{op.name}' переопределяет несуществующий элемент '{op.redefines}' в родителях"
                        )

    def validate_parameter_type_references(self) -> None:
        """Проверяем, что типы параметров и возвращаемые типы либо примитивы,
        либо известные классификаторы на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            template_type_names = {
                tp.name for tp in (getattr(cls, "template_parameters", None) or [])
            }
            for op in cls.operations:
                for p in op.parameters:
                    if not p.type_:
                        continue
                    if p.type_ in prim_names:
                        continue
                    if p.type_ in template_type_names:
                        continue
                    if p.type_ not in known:
                        raise ValueError(
                            f"Параметр '{p.name}' операции '{op.name}' класса '{cls_name}' ссылается на неизвестный тип '{p.type_}'"
                        )
                    target = self.classifiers.get(p.type_)
                    if not isinstance(target, Class):
                        raise ValueError(
                            f"Параметр '{p.name}' операции '{op.name}' класса '{cls_name}' ссылается на тип '{p.type_}', который не является Class"
                        )
                # return type
                if op.return_type:
                    if op.return_type in prim_names:
                        continue
                    if op.return_type in template_type_names:
                        continue
                    if op.return_type not in known:
                        raise ValueError(
                            f"Операция '{op.name}' класса '{cls_name}' имеет неизвестный возвращаемый тип '{op.return_type}'"
                        )
                    ret_target = self.classifiers.get(op.return_type)
                    if not isinstance(ret_target, Class):
                        raise ValueError(
                            f"Операция '{op.name}' класса '{cls_name}' имеет возвращаемый тип '{op.return_type}', который не является Class"
                        )

    def validate_template_parameter_type_references(self) -> None:
        """Проверяем, что для каждого параметра шаблона его `type_` и
        `default_value` либо примитив, либо известный классификатор на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            tpl_params = getattr(cls, "template_parameters", None) or []
            for tp in tpl_params:
                # type_ check
                if tp.type_:
                    if tp.type_ in prim_names:
                        pass
                    elif tp.type_ not in known:
                        raise ValueError(
                            f"Параметр шаблона '{tp.name}' класса '{cls_name}' ссылается на неизвестный тип '{tp.type_}'"
                        )
                    else:
                        target = self.classifiers.get(tp.type_)
                        if not isinstance(target, Class):
                            raise ValueError(
                                f"Параметр шаблона '{tp.name}' класса '{cls_name}' ссылается на тип '{tp.type_}', который не является Class"
                            )
                # default_value check — interpreted as a type name when present
                if tp.default_value:
                    if tp.default_value in prim_names:
                        pass
                    elif tp.default_value not in known:
                        raise ValueError(
                            f"Параметр шаблона '{tp.name}' класса '{cls_name}' имеет неизвестное значение по умолчанию типа '{tp.default_value}'"
                        )
                    else:
                        dv_target = self.classifiers.get(tp.default_value)
                        if not isinstance(dv_target, Class):
                            raise ValueError(
                                f"Параметр шаблона '{tp.name}' класса '{cls_name}' имеет значение по умолчанию типа '{tp.default_value}', который не является Class"
                            )

    def validate_template_binding_references(self) -> None:
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for binding in self.template_bindings:
            bound_name = binding.bound_element.name
            template_name = binding.template.name
            if bound_name not in known:
                raise ValueError(
                    f"Подстановка шаблона ссылается на неизвестный bound element '{bound_name}'"
                )
            if template_name not in known:
                raise ValueError(
                    f"Подстановка шаблона ссылается на неизвестный шаблон '{template_name}'"
                )

            template = self.classifiers[template_name]
            template_params = {
                tp.name for tp in (getattr(template, "template_parameters", None) or [])
            }
            if template_params:
                for formal in binding.substitutions:
                    if formal not in template_params:
                        raise ValueError(
                            f"Подстановка шаблона '{bound_name}->{template_name}' "
                            f"указывает неизвестный параметр '{formal}'"
                        )

            for actual in binding.substitutions.values():
                if actual in prim_names:
                    continue
                if actual not in known:
                    raise ValueError(
                        f"Подстановка шаблона '{bound_name}->{template_name}' "
                        f"ссылается на неизвестный actual type '{actual}'"
                    )

    def validate_attribute_type_references(self) -> None:
        """Проверяем, что для каждого атрибута ссылаемый тип либо примитив, либо
        известный классификатор на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            template_type_names = {
                tp.name for tp in (getattr(cls, "template_parameters", None) or [])
            }
            for attr in cls.attributes:
                if not attr.type_:
                    continue
                if attr.type_ in prim_names:
                    continue
                if attr.type_ in template_type_names:
                    continue
                if attr.type_ not in known:
                    raise ValueError(
                        f"Атрибут '{attr.name}' класса '{cls_name}' ссылается на неизвестный тип '{attr.type_}'"
                    )

    # ──── Layout ───────────────────────────────────────────────────────

    def auto_layout(
        self,
        cols: int = 3,
        spacing_x: int = 300,
        spacing_y: int = 250,
        start_x: int = 40,
        start_y: int = 40,
    ) -> None:
        """Простая сеточная раскладка классов."""
        names = list(self.classifiers.keys())
        for idx, name in enumerate(names):
            cls = self.classifiers[name]
            w, h = cls.get_box_size()
            row = idx // cols
            col = idx % cols
            x = start_x + col * spacing_x
            y = start_y + row * spacing_y
            self.positions[name] = ClassPosition(
                classifier_name=name, x=x, y=y, width=w, height=h,
            )

    # ──── SVG рендеринг ─────────────────────────────────────────────────


    def to_svg(
        self,
        width: int = 1400,
        height: int = 900,
        interactive: bool = False,
        theme: str = "light",
    ) -> str:
        """Render the diagram through the Graphviz-based SVG pipeline.

        The size and interactive arguments are kept for compatibility with older
        callers; layout and dimensions are now produced by graphviz_render.
        """
        from .graphviz_render import diagram_to_graphviz_svg

        return diagram_to_graphviz_svg(self, theme=theme)
