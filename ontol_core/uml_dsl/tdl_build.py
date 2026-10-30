# Сборка ClassDiagram из AST TDL и применение размещения
from __future__ import annotations

from typing import Optional

from .diagram import ClassDiagram, ClassPosition
from .enums import Changeability, DependencyStereotype, Scope, Visibility, Stereotype, AggregationKind
from .models import (
    Attribute,
    Class,
    DataType,
    Interface,
    MultiplicityRange,
    Operation,
    Parameter,
    Template,
    TemplateParameter,
)
from .relationships import (
    Association,
    AssociationClass,
    AssociationEnd,
    Dependency,
    Generalization,
    Realization,
    TemplateBinding,
)
from .tdl_ast import (
    AlignCmd,
    AssociationClassDecl,
    AssociationDecl,
    BindCmd,
    ClassDecl,
    DataTypeDecl,
    EnumDecl,
    DependencyDecl,
    DistributeCmd,
    Document,
    FixCmd,
    GeneralizationDecl,
    InterfaceDecl,
    RealizationDecl,
    TemplateBindingDecl,
    TemplateDecl,
)


def _visibility(s: Optional[str]):
    if s is None:
        return None
    return {"+": Visibility.PUBLIC, "-": Visibility.PRIVATE, "#": Visibility.PROTECTED, "~": Visibility.PACKAGE}.get(s)


def _parse_multiplicity(s: Optional[str]) -> Optional[MultiplicityRange]:
    if not s:
        return None  # не указана — подразумевается по умолчанию, не рисуем
    if s == "*":
        return MultiplicityRange(lower=0, upper=None)
    if ".." in s:
        parts = s.split("..")
        lo = int(parts[0].strip())
        up = None if parts[1].strip() == "*" else int(parts[1].strip())
        return MultiplicityRange(lower=lo, upper=up)
    n = int(s)
    return MultiplicityRange(lower=n, upper=n)


def _map_type(t: Optional[str]) -> Optional[str]:
    """Русские/альтернативные имена типов → имена из модели."""
    if not t:
        return t
    m = {"Строка": "String", "строка": "String", "цел": "int", "целый": "int"}
    return m.get(t, t)


def _dep_stereotype(s: Optional[str]):
    if not s:
        return None
    m = {
        "bind": DependencyStereotype.BIND,
        "связывание": DependencyStereotype.BIND,
        "подстановка": DependencyStereotype.BIND,
        "use": DependencyStereotype.USE,
        "использование": DependencyStereotype.USE,
        "call": DependencyStereotype.CALL,
        "вызов": DependencyStereotype.CALL,
        "instanceof": DependencyStereotype.INSTANCE_OF,
        "экземпляр": DependencyStereotype.INSTANCE_OF,
    }
    return m.get(s.lower())


def _build_attributes(decl_attrs):
    attrs = []
    for a in decl_attrs:
        mult = _parse_multiplicity(a.multiplicity)
        change = Changeability.READ_ONLY if a.only_read else None
        initial = a.default
        if initial and a.type_ and a.type_.lower() in ("цел", "int", "integer"):
            try:
                initial = int(initial)
            except ValueError:
                pass
        attrs.append(
            Attribute(
                name=a.name,
                visibility=_visibility(a.visibility),
                type_=_map_type(a.type_),
                multiplicity=mult,
                initial_value=initial,
                changeability=change,
            )
        )
    return attrs


def _build_operations(
    decl_ops,
    *,
    force_abstract: bool = False,
    force_query: bool = False,
    force_classifier_scope: bool = False,
):
    ops = []
    for o in decl_ops:
        params = [
            Parameter(
                name=p.name,
                type_=_map_type(p.type_),
                default=p.default,
            )
            for p in o.params
        ]
        ops.append(
            Operation(
                name=o.name,
                visibility=_visibility(o.visibility),
                parameters=params,
                return_type=_map_type(o.return_type),
                is_abstract=force_abstract or o.is_abstract,
                is_query=force_query or o.is_query,
                is_leaf=o.is_leaf,
                scope=Scope.CLASSIFIER if force_classifier_scope else Scope.INSTANCE,
            )
        )
    return ops


def _build_template_parameters(decl_params):
    return [
        TemplateParameter(
            name=param.name,
            type_=_map_type(param.type_),
            default_value=_map_type(param.default),
        )
        for param in decl_params
    ]


def _build_association(diagram: ClassDiagram, decl: AssociationDecl) -> Association:
    c1 = diagram.classifiers.get(decl.end1.participant)
    c2 = diagram.classifiers.get(decl.end2.participant)
    if c1 is None or c2 is None:
        raise ValueError(
            f"Участник ассоциации не найден: {decl.end1.participant} или {decl.end2.participant}"
        )

    agg1 = AggregationKind.NONE
    if decl.aggregation == "composition":
        agg1 = AggregationKind.COMPOSITION
    elif decl.aggregation == "aggregation":
        agg1 = AggregationKind.AGGREGATION

    e1 = AssociationEnd(
        participant=c1,
        multiplicity=_parse_multiplicity(decl.end1.multiplicity),
        role=decl.end1.role,
        navigable=True,
        aggregation=agg1,
    )

    e2 = AssociationEnd(
        participant=c2,
        multiplicity=_parse_multiplicity(decl.end2.multiplicity),
        role=decl.end2.role,
        navigable=False,
        aggregation=AggregationKind.NONE,
    )

    return Association(ends=[e1, e2], name=decl.name, is_derived=decl.is_derived)


def build_diagram(doc: Document, title: str = "Диаграмма TDL") -> ClassDiagram:
    diagram = ClassDiagram(title=title)
    # 1) Классы
    for decl in doc.declarations:
        if isinstance(decl, EnumDecl):
            enum_attrs = [
                Attribute(name=value)
                for value in decl.literals
            ]

            enum_cls = Class(
                name=decl.name,
                stereotype=Stereotype.ENUMERATION,
                attributes=enum_attrs,
                operations=[],
            )

            diagram.add_classifier(enum_cls)
        if isinstance(decl, ClassDecl):
            cls = Class(
                name=decl.name,
                is_abstract=decl.is_abstract,
                attributes=_build_attributes(decl.attributes),
                operations=_build_operations(decl.operations),
            )
            diagram.add_classifier(cls)
        if isinstance(decl, InterfaceDecl):
            interface = Interface(
                name=decl.name,
                attributes=_build_attributes(decl.attributes),
                operations=_build_operations(decl.operations, force_abstract=True),
            )
            diagram.add_classifier(interface)
        if isinstance(decl, DataTypeDecl):
            data_type = DataType(
                name=decl.name,
                attributes=_build_attributes(decl.attributes),
                operations=_build_operations(
                    decl.operations,
                    force_query=True,
                    force_classifier_scope=True,
                ),
            )
            diagram.add_classifier(data_type)
        if isinstance(decl, TemplateDecl):
            template = Template(
                name=decl.name,
                template_parameters=_build_template_parameters(decl.template_parameters),
                attributes=_build_attributes(decl.attributes),
                operations=_build_operations(decl.operations),
            )
            diagram.add_classifier(template)
        if isinstance(decl, AssociationClassDecl):
            assoc_cls = Class(
                name=decl.name,
                attributes=_build_attributes(decl.attributes),
                operations=_build_operations(decl.operations),
            )
            diagram.add_classifier(assoc_cls)

    # 2) Отношения
    for decl in doc.declarations:
        if isinstance(decl, GeneralizationDecl):
            diagram.add_generalization(decl.specific, decl.general, is_substitutable=decl.substitutable)
        elif isinstance(decl, DependencyDecl):
            diagram.add_dependency(
                client=decl.client,
                supplier=decl.supplier,
                stereotype=_dep_stereotype(decl.stereotype),
            )
        elif isinstance(decl, TemplateBindingDecl):
            bound_element = diagram.classifiers.get(decl.bound_element)
            template = diagram.classifiers.get(decl.template)
            if not isinstance(bound_element, Class):
                raise ValueError(
                    f"Bound element шаблона не найден: {decl.bound_element}"
                )
            if not isinstance(template, Class):
                raise ValueError(f"Шаблон не найден: {decl.template}")
            diagram.add_template_binding(
                TemplateBinding(
                    bound_element=bound_element,
                    template=template,
                    substitutions={
                        item.name: _map_type(item.default) or ""
                        for item in decl.substitutions
                    },
                )
            )
        elif isinstance(decl, RealizationDecl):
            diagram.add_realization(implementing=decl.implementer, interface=decl.interface)
        elif isinstance(decl, AssociationClassDecl):
            assoc = _build_association(diagram, decl.association)
            associated_classifier = diagram.classifiers.get(decl.name)
            if not isinstance(associated_classifier, Class):
                raise ValueError(
                    f"Класс ассоциации '{decl.name}' не найден как классификатор"
                )
            diagram.add_association_class(
                AssociationClass(
                    ends=assoc.ends,
                    name=assoc.name,
                    is_derived=assoc.is_derived,
                    associated_classifier=associated_classifier,
                )
            )
        elif isinstance(decl, AssociationDecl):
            diagram.add_association(_build_association(diagram, decl))

    # 3) Размещение
    if doc.layout and doc.layout.commands:
        for cmd in doc.layout.commands:
            if isinstance(cmd, FixCmd):
                cls = diagram.classifiers.get(cmd.element)
                if cls:
                    w, h = cls.get_box_size()
                    diagram.positions[cmd.element] = ClassPosition(
                        classifier_name=cmd.element, x=cmd.x, y=cmd.y, width=w, height=h
                    )
        placed = set(diagram.positions.keys())
        unplaced = [n for n in diagram.classifiers if n not in placed]
        if unplaced:
            for idx, name in enumerate(unplaced):
                cls = diagram.classifiers[name]
                w, h = cls.get_box_size()
                row = idx // 3
                col = idx % 3
                diagram.positions[name] = ClassPosition(
                    classifier_name=name,
                    x=40 + col * 380,
                    y=40 + row * 280,
                    width=w,
                    height=h,
                )
    else:
        diagram.auto_layout(cols=3, spacing_x=380, spacing_y=280, start_x=40, start_y=40)

    return diagram
