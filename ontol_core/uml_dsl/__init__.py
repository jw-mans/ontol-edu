# UML DSL — текстовый язык описания диаграмм классов UML
# Разработан на базе Pydantic v2 с поддержкой рендеринга в интерактивный SVG

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
    Attribute,
    Classifier,
    Class,
    DataType,
    Interface,
    Template,
    ClassFeature,
    ModelElement,
    Multiplicity,
    MultiplicityRange,
    Operation,
    Parameter,
    TaggedValue,
    TemplateParameter,
)
from .relationships import (
    Association,
    AssociationClass,
    AssociationEnd,
    Dependency,
    Generalization,
    GeneralizationSet,
    Realization,
    TemplateBinding,
    
)
from .diagram import ClassDiagram, ClassPosition

try:
    from .export import svg_to_png, svg_to_jpg, export_available
except (ImportError, OSError):
    svg_to_png = None  # type: ignore
    svg_to_jpg = None  # type: ignore
    export_available = lambda: False  # type: ignore

__all__ = [
    # Enums
    "AggregationKind",
    "Changeability",
    "CollectionKind",
    "Concurrency",
    "DependencyStereotype",
    "ParamDirection",
    "Scope",
    "Stereotype",
    "Visibility",
    # Models
    "Attribute",
    "Classifier",
    "Class",
    "DataType",
    "Interface",
    "Template",
    "ClassFeature",
    "ModelElement",
    "Multiplicity",
    "MultiplicityRange",
    "Operation",
    "Parameter",
    "TaggedValue",
    "TemplateParameter",
    # Relationships
    "Association",
    "AssociationClass",
    "AssociationEnd",
    "Dependency",
    "Generalization",
    "GeneralizationSet",
    "Realization",
    "TemplateBinding",
    
    # Diagram
    "ClassDiagram",
    "ClassPosition",
    # Export
    "svg_to_png",
    "svg_to_jpg",
    "export_available",
]
