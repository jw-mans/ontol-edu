"""
Парсер SVG с data-атрибутами обратно в Pydantic-модель UML.
Использует BeautifulSoup для парсинга XML.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Any

from pydantic import BaseModel, Field, ValidationError

from .enums import (
    AggregationKind,
    Changeability,
    CollectionKind,
    Concurrency,
    DependencyStereotype,
    ParamDirection,
    Scope,
    Stereotype,
    Visibility,
)
from .models import (
    Class,
    DataType,
    Interface,
    Attribute,
    Operation,
    Parameter,
    Multiplicity,
    MultiplicityRange,
    TaggedValue,
    Template,
    TemplateParameter,
)
from .relationships import (
    Association, AssociationClass, AssociationEnd, Dependency,
    Generalization, Realization, TemplateBinding,
)
from .diagram import ClassDiagram, ClassPosition


class ParseResult(BaseModel):
    """Результат парсинга SVG в Pydantic-модель."""
    success: bool
    diagram: Optional[ClassDiagram] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def parse_transform(transform_str: str) -> Tuple[float, float]:
    """Извлекает координаты из transform="translate(x,y)"."""
    if not transform_str or "translate" not in transform_str:
        return (0.0, 0.0)
    # translate(10,20) или translate(10 20)
    import re
    match = re.search(r'translate\(([^,)]+)[,\s]+([^)]+)\)', transform_str)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    return (0.0, 0.0)


def _data_attr(elem: ET.Element, *names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = elem.get(name)
        if value not in (None, ""):
            return value
    return default


def _parse_optional_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return {"true": True, "false": False}.get(value.lower())


def _parse_bool(value: Optional[str], *, default: bool = False) -> bool:
    parsed = _parse_optional_bool(value)
    return default if parsed is None else parsed


def _indexed(elements: List[ET.Element]) -> List[ET.Element]:
    def key(elem: ET.Element) -> int:
        raw = elem.get("data-index")
        try:
            return int(raw or "0")
        except ValueError:
            return 0

    return sorted(elements, key=key)


def _enum_value(enum_cls, raw: Optional[str], label: str):
    if raw in (None, ""):
        return None
    try:
        return enum_cls(raw)
    except ValueError as exc:
        raise ValueError(f"{label}: unknown value '{raw}'") from exc


def _parse_primitive_value(kind: Optional[str], raw: Optional[str], has_value: bool) -> Any:
    if not has_value:
        return None

    value = "" if raw is None else raw
    kind = kind or "str"

    if kind == "none":
        return None
    if kind == "bool":
        return value.lower() == "true"
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return value


def _parse_multiplicity_range(value: Optional[str]) -> Optional[MultiplicityRange]:
    if not value:
        return None
    return MultiplicityRange.from_str(value)


def _parse_multiplicity(value: Optional[str]) -> Optional[Multiplicity]:
    if not value:
        return None
    ranges = [
        MultiplicityRange.from_str(part.strip())
        for part in value.split(",")
        if part.strip()
    ]
    return Multiplicity(ranges=ranges) if ranges else None


def _class_bbox(elem: ET.Element) -> tuple[float, float]:
    rects = elem.findall(".//rect")

    for rect in rects:
        classes = (rect.get("class") or "").split()
        if "uml-bbox" in classes:
            return float(rect.get("width", "120")), float(rect.get("height", "60"))

    if rects:
        rect = rects[0]
        return float(rect.get("width", "120")), float(rect.get("height", "60"))

    return 120.0, 60.0


def _parse_attribute_element(elem: ET.Element, label: str) -> Attribute:
    has_initial = _parse_bool(elem.get("data-has-initial-value"))
    initial_value = _parse_primitive_value(
        elem.get("data-initial-value-kind"),
        elem.get("data-initial-value"),
        has_initial,
    )

    return Attribute(
        name=elem.get("data-name") or "",
        visibility=_enum_value(Visibility, elem.get("data-visibility"), f"{label} visibility"),
        scope=_enum_value(Scope, elem.get("data-scope"), f"{label} scope") or Scope.INSTANCE,
        type_=elem.get("data-value-type") or None,
        multiplicity=_parse_multiplicity_range(elem.get("data-multiplicity")),
        initial_value=initial_value,
        changeability=_enum_value(Changeability, elem.get("data-changeability"), f"{label} changeability"),
        redefines=elem.get("data-redefines") or None,
    )


def _parse_parameter_element(elem: ET.Element, label: str) -> Parameter:
    has_default = _parse_bool(elem.get("data-has-default"))
    default = _parse_primitive_value(
        elem.get("data-default-kind"),
        elem.get("data-default"),
        has_default,
    )

    return Parameter(
        name=elem.get("data-name") or "",
        type_=elem.get("data-parameter-type") or None,
        direction=_enum_value(ParamDirection, elem.get("data-direction"), f"{label} direction") or ParamDirection.IN,
        default=default,
    )


def _parse_operation_element(elem: ET.Element, label: str) -> Operation:
    params = [
        _parse_parameter_element(param, f"{label} parameter")
        for param in _indexed(elem.findall('.//*[@data-type="operation-parameter"]'))
    ]

    return Operation(
        name=elem.get("data-name") or "",
        visibility=_enum_value(Visibility, elem.get("data-visibility"), f"{label} visibility"),
        scope=_enum_value(Scope, elem.get("data-scope"), f"{label} scope") or Scope.INSTANCE,
        parameters=params,
        return_type=elem.get("data-return-type") or None,
        is_abstract=_parse_bool(elem.get("data-abstract")),
        is_query=_parse_bool(elem.get("data-query")),
        concurrency=_enum_value(Concurrency, elem.get("data-concurrency"), f"{label} concurrency") or Concurrency.SEQUENTIAL,
        is_leaf=_parse_bool(elem.get("data-leaf")),
        redefines=elem.get("data-redefines") or None,
    )


def _parse_tagged_value_element(elem: ET.Element, label: str) -> TaggedValue:
    value = _parse_primitive_value(
        elem.get("data-value-kind"),
        elem.get("data-value"),
        _parse_bool(elem.get("data-has-value")),
    )
    return TaggedValue(name=elem.get("data-name") or "", value=value)


def _parse_template_parameter_element(elem: ET.Element, label: str) -> TemplateParameter:
    return TemplateParameter(
        name=elem.get("data-name") or "",
        type_=elem.get("data-parameter-type") or None,
        default_value=elem.get("data-default-value") if _parse_bool(elem.get("data-has-default-value")) else None,
    )


def _parse_int_attr(elem: ET.Element, name: str, *, default: int = 0) -> int:
    try:
        return int(elem.get(name, str(default)) or str(default))
    except ValueError:
        return default


def parse_svg_to_diagram(svg_content: str, *, validate: bool = True) -> ParseResult:
    """
    Парсит SVG с data-атрибутами и восстанавливает ClassDiagram.
    
    Собирает ошибки и предупреждения вместо выбрасывания исключений.
    
    Args:
        svg_content: содержимое SVG-файла
        
    Returns:
        ParseResult с диаграммой, ошибками и предупреждениями
    """
    errors: List[str] = []
    warnings: List[str] = []
    
    try:
        root = ET.fromstring(svg_content)
    except ET.ParseError as e:
        return ParseResult(
            success=False,
            errors=[f"Ошибка парсинга XML: {e}"]
        )
    
    # Проверка наличия классов
    class_elements = root.findall('.//*[@data-type="class"]')
    if not class_elements:
        return ParseResult(
            success=False,
            errors=["Диаграмма не содержит размеченных классов. Убедитесь, что SVG сгенерирован TDL."]
        )
    
    # Создаём пустую диаграмму
    diagram = ClassDiagram(title=root.get("data-title") or "Imported from SVG")
    
    # 1. Сначала парсим все классы (они нужны для ссылок в отношениях)
    class_positions = {}
    
    for elem in class_elements:
        class_id = elem.get('data-id')
        if not class_id:
            errors.append(f"Класс без атрибута data-id (элемент {elem.tag})")
            continue
            
        # Извлекаем данные из атрибутов
        name = elem.get('data-name', class_id)

        if name in diagram.classifiers:
            errors.append(f"Дублирование классификатора '{name}'")
            continue

        try:
            stereotype = _enum_value(Stereotype, elem.get('data-stereotype'), f"Класс '{name}' stereotype")
            attributes = [
                _parse_attribute_element(attr, f"Класс '{name}' атрибут")
                for attr in _indexed(elem.findall('.//*[@data-type="attribute"]'))
            ]
            operations = [
                _parse_operation_element(op, f"Класс '{name}' операция")
                for op in _indexed(elem.findall('.//*[@data-type="operation"]'))
            ]
            tagged_values = [
                _parse_tagged_value_element(tv, f"Класс '{name}' tagged value")
                for tv in _indexed(elem.findall('./*[@data-type="tagged-value"]'))
            ]
            template_parameters = [
                _parse_template_parameter_element(tp, f"Класс '{name}' template parameter")
                for tp in _indexed(elem.findall('./*[@data-type="template-parameter"]'))
            ]

            enum_literals = [
                literal.get("data-name") or (literal.text or "").strip()
                for literal in _indexed(elem.findall('.//*[@data-type="enum-literal"]'))
            ]
            if stereotype == Stereotype.ENUMERATION and enum_literals:
                attributes = [Attribute(name=value) for value in enum_literals if value]

            class_kwargs = dict(
                name=name,
                visibility=_enum_value(Visibility, elem.get("data-visibility"), f"Класс '{name}' visibility"),
                multiplicity=_parse_multiplicity(elem.get("data-multiplicity")),
                stereotype=stereotype,
                is_abstract=_parse_bool(elem.get('data-abstract')),
                attributes=attributes,
                operations=operations,
                tagged_values=tagged_values,
            )

            class_kind = elem.get("data-class-kind")
            if class_kind == "template" or template_parameters:
                cls = Template(**class_kwargs, template_parameters=template_parameters)
            elif class_kind == "interface" or stereotype == Stereotype.INTERFACE:
                cls = Interface(**class_kwargs)
            elif class_kind == "dataType" or stereotype == Stereotype.DATA_TYPE:
                cls = DataType(**class_kwargs)
            else:
                cls = Class(**class_kwargs)

            diagram.add_classifier(cls)
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Класс '{name}' is invalid: {e}")
            continue

        attr_count = _parse_int_attr(elem, 'data-attributes-count')
        op_count = _parse_int_attr(elem, 'data-operations-count')
        if attr_count and not getattr(cls, "attributes", []):
            warnings.append(f"Класс '{name}': SVG сообщает {attr_count} атрибут(ов), но структурные data-атрибуты не найдены")
        if op_count and not getattr(cls, "operations", []):
            warnings.append(f"Класс '{name}': SVG сообщает {op_count} операцию(й), но структурные data-атрибуты не найдены")
        
        # Сохраняем позицию
        transform = elem.get('transform', '')
        x, y = parse_transform(transform)
        
        width, height = _class_bbox(elem)
            
        class_positions[name] = ClassPosition(
            classifier_name=name,
            x=x, y=y,
            width=width, height=height
        )
    
    # Добавляем все позиции в диаграмму
    diagram.positions.update(class_positions)
    diagram.manual_layout = True
    
    def parse_association_element(elem: ET.Element, label: str) -> Optional[Association]:
        src = _data_attr(elem, 'data-end1-class', 'data-src')
        tgt = _data_attr(elem, 'data-end2-class', 'data-tgt')

        if not src or not tgt:
            warnings.append(
                f"{label} without data-end1-class/data-end2-class or legacy data-src/data-tgt ignored"
            )
            return None

        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)

        if not src_cls:
            errors.append(f"{label}: класс-источник '{src}' не найден")
            return None
        if not tgt_cls:
            errors.append(f"{label}: класс-целевой '{tgt}' не найден")
            return None

        try:
            def qualifier_elements(end_index: int) -> List[ET.Element]:
                return [
                    qualifier
                    for qualifier in elem.findall('.//*[@data-type="association-end-qualifier"]')
                    if qualifier.get("data-end") == str(end_index)
                ]

            def role_type(prefix: str):
                raw = _data_attr(elem, f'{prefix}-role-type')
                if not raw:
                    return None
                target = diagram.classifiers.get(raw)
                if target is None:
                    raise ValueError(f"unknown role_type '{raw}'")
                if not isinstance(target, Class):
                    raise ValueError(f"role_type '{raw}' is not Class")
                return target

            end1 = AssociationEnd(
                participant=src_cls,
                multiplicity=_parse_multiplicity_range(_data_attr(elem, 'data-end1-multiplicity', 'data-src-multiplicity')),
                aggregation=_enum_value(
                    AggregationKind,
                    _data_attr(elem, 'data-end1-aggregation', 'data-src-aggregation', default='none') or 'none',
                    f"Association '{src}->{tgt}' end1 aggregation",
                ) or AggregationKind.NONE,
                role=_data_attr(elem, 'data-end1-role', 'data-src-role'),
                navigable=_parse_optional_bool(_data_attr(elem, 'data-end1-navigable', 'data-src-navigable')),
                role_visibility=_enum_value(Visibility, _data_attr(elem, 'data-end1-role-visibility'), f"{label} '{src}->{tgt}' end1 role_visibility"),
                collection_kind=_enum_value(CollectionKind, _data_attr(elem, 'data-end1-collection-kind'), f"{label} '{src}->{tgt}' end1 collection_kind") or CollectionKind.SET,
                changeability=_enum_value(Changeability, _data_attr(elem, 'data-end1-changeability'), f"{label} '{src}->{tgt}' end1 changeability"),
                qualifiers=[
                    _parse_attribute_element(qualifier, f"{label} '{src}->{tgt}' end1 qualifier")
                    for qualifier in _indexed(qualifier_elements(1))
                ],
                is_derived=_parse_bool(_data_attr(elem, 'data-end1-derived')),
                is_union=_parse_bool(_data_attr(elem, 'data-end1-union')),
                redefines=_data_attr(elem, 'data-end1-redefines'),
                role_type=role_type('data-end1'),
            )

            end2 = AssociationEnd(
                participant=tgt_cls,
                multiplicity=_parse_multiplicity_range(_data_attr(elem, 'data-end2-multiplicity', 'data-tgt-multiplicity')),
                aggregation=_enum_value(
                    AggregationKind,
                    _data_attr(elem, 'data-end2-aggregation', 'data-tgt-aggregation', default='none') or 'none',
                    f"Association '{src}->{tgt}' end2 aggregation",
                ) or AggregationKind.NONE,
                role=_data_attr(elem, 'data-end2-role', 'data-tgt-role'),
                navigable=_parse_optional_bool(_data_attr(elem, 'data-end2-navigable', 'data-tgt-navigable')),
                role_visibility=_enum_value(Visibility, _data_attr(elem, 'data-end2-role-visibility'), f"{label} '{src}->{tgt}' end2 role_visibility"),
                collection_kind=_enum_value(CollectionKind, _data_attr(elem, 'data-end2-collection-kind'), f"{label} '{src}->{tgt}' end2 collection_kind") or CollectionKind.SET,
                changeability=_enum_value(Changeability, _data_attr(elem, 'data-end2-changeability'), f"{label} '{src}->{tgt}' end2 changeability"),
                qualifiers=[
                    _parse_attribute_element(qualifier, f"{label} '{src}->{tgt}' end2 qualifier")
                    for qualifier in _indexed(qualifier_elements(2))
                ],
                is_derived=_parse_bool(_data_attr(elem, 'data-end2-derived')),
                is_union=_parse_bool(_data_attr(elem, 'data-end2-union')),
                redefines=_data_attr(elem, 'data-end2-redefines'),
                role_type=role_type('data-end2'),
            )

            def apply_subset(end: AssociationEnd, prefix: str) -> None:
                subset_role = _data_attr(elem, f'{prefix}-subsets-role')
                subset_participant = _data_attr(elem, f'{prefix}-subsets-participant')
                if not subset_role and not subset_participant:
                    return

                for candidate in (end1, end2):
                    if subset_role and candidate.role == subset_role:
                        end.subsets = candidate
                        return
                    if subset_participant and candidate.participant.name == subset_participant:
                        end.subsets = candidate
                        return
                raise ValueError(f"unknown subsets target '{subset_role or subset_participant}'")

            apply_subset(end1, 'data-end1')
            apply_subset(end2, 'data-end2')

            assoc = Association(
                name=elem.get('data-name'),
                is_derived=elem.get('data-derived') == 'true',
                ends=[end1, end2]
            )
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"{label} '{src}->{tgt}' is invalid: {e}")
            return None

        return assoc

    # 2. Парсим отношения (ассоциации)
    for elem in root.findall('.//*[@data-type="association"]'):
        assoc = parse_association_element(elem, "Association")
        if assoc is None:
            continue

        diagram.add_association(assoc)

    # 2.1. Парсим классы ассоциаций
    for elem in root.findall('.//*[@data-type="association-class"]'):
        assoc = parse_association_element(elem, "Association class")
        if assoc is None:
            continue

        associated_name = _data_attr(
            elem,
            'data-associated-classifier',
            'data-association-classifier',
        )
        if not associated_name:
            errors.append("Association class without data-associated-classifier")
            continue

        associated_classifier = diagram.classifiers.get(associated_name)
        if not associated_classifier:
            errors.append(
                f"Association class: связанный классификатор '{associated_name}' не найден"
            )
            continue
        if not isinstance(associated_classifier, Class):
            errors.append(
                f"Association class: связанный классификатор '{associated_name}' не является Class"
            )
            continue

        try:
            diagram.add_association_class(
                AssociationClass(
                    name=assoc.name,
                    is_derived=assoc.is_derived,
                    ends=assoc.ends,
                    associated_classifier=associated_classifier,
                )
            )
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(
                f"Association class '{associated_name}' is invalid: {e}"
            )
    
    # 3. Парсим подстановки шаблонов
    for elem in root.findall('.//*[@data-type="template-binding"]'):
        bound_name = elem.get('data-bound-element')
        template_name = elem.get('data-template')

        if not bound_name or not template_name:
            warnings.append("Template binding without data-bound-element/data-template ignored")
            continue

        bound_element = diagram.classifiers.get(bound_name)
        template = diagram.classifiers.get(template_name)

        if not isinstance(bound_element, Class):
            errors.append(f"Template binding: bound element '{bound_name}' не найден")
            continue
        if not isinstance(template, Class):
            errors.append(f"Template binding: template '{template_name}' не найден")
            continue

        substitutions = {
            sub.get("data-formal") or "": sub.get("data-actual") or ""
            for sub in _indexed(elem.findall('./*[@data-type="template-substitution"]'))
        }
        substitutions = {
            formal: actual
            for formal, actual in substitutions.items()
            if formal and actual
        }

        try:
            diagram.add_template_binding(
                TemplateBinding(
                    bound_element=bound_element,
                    template=template,
                    substitutions=substitutions,
                )
            )
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Template binding '{bound_name}->{template_name}' is invalid: {e}")

    # 4. Парсим зависимости
    for elem in root.findall('.//*[@data-type="dependency"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Зависимость без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Зависимость: класс-клиент '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Зависимость: класс-поставщик '{tgt}' не найден")
            continue
        
        try:
            stereo = elem.get('data-stereotype')
            dep = Dependency(
                client=src_cls,
                supplier=tgt_cls,
                stereotype=_enum_value(DependencyStereotype, stereo, f"Dependency '{src}->{tgt}' stereotype"),
            )
            diagram.dependencies.append(dep)
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Dependency '{src}->{tgt}' is invalid: {e}")
    
    # 4. Парсим обобщения
    for elem in root.findall('.//*[@data-type="generalization"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Обобщение без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Обобщение: класс-частный '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Обобщение: класс-общий '{tgt}' не найден")
            continue
        
        try:
            gen = Generalization(
                specific=src_cls,
                general=tgt_cls,
                is_substitutable=elem.get('data-substitutable') != 'false'
            )
            diagram.generalizations.append(gen)
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Generalization '{src}->{tgt}' is invalid: {e}")
    
    # 5. Парсим реализации
    for elem in root.findall('.//*[@data-type="realization"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Реализация без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Реализация: класс-реализатор '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Реализация: интерфейс '{tgt}' не найден")
            continue
        
        try:
            real = Realization(
                implementer=src_cls,
                interface_=tgt_cls
            )
            diagram.realizations.append(real)
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Realization '{src}->{tgt}' is invalid: {e}")

    if validate and not errors:
        try:
            diagram.validate_all()
        except (ValueError, IndexError, ValidationError) as e:
            errors.append(f"Ошибка валидации диаграммы: {e}")
    
    # Возвращаем результат с диаграммой и любыми накопленными предупреждениями
    return ParseResult(
        success=not errors,
        diagram=diagram,
        warnings=warnings if not errors else [],  # не включаем предупреждения если были ошибки
        errors=errors
    )


# Добавляем вспомогательный метод в MultiplicityRange
def multiplicity_range_from_str(s: str) -> MultiplicityRange:
    """Парсит строку вида '1..*' или '0..1' или '*'."""
    if not s:
        return MultiplicityRange(lower=0, upper=None)
    
    if s == '*':
        return MultiplicityRange(lower=0, upper=None)
    
    if '..' in s:
        parts = s.split('..')
        lower = int(parts[0])
        upper = None if parts[1] == '*' else int(parts[1])
        return MultiplicityRange(lower=lower, upper=upper)
    
    # Одиночное число
    val = int(s)
    return MultiplicityRange(lower=val, upper=val)

# Monkey-patch для удобства
MultiplicityRange.from_str = staticmethod(multiplicity_range_from_str)
