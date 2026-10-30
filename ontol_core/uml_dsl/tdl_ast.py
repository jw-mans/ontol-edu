# AST для TDL
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class AttributeLine:
    visibility: Optional[str]
    name: str
    multiplicity: Optional[str] = None
    type_: Optional[str] = None
    default: Optional[str] = None
    only_read: bool = False

@dataclass
class ParameterLine:
    name: str
    type_: Optional[str] = None
    default: Optional[str] = None

@dataclass
class OperationLine:
    visibility: Optional[str]
    name: str
    params: List[ParameterLine] = field(default_factory=list)
    return_type: Optional[str] = None
    is_abstract: bool = False
    is_query: bool = False
    is_leaf: bool = False


@dataclass
class ClassDecl:
    name: str
    is_abstract: bool = False
    attributes: List[AttributeLine] = field(default_factory=list)
    operations: List[OperationLine] = field(default_factory=list)

@dataclass
class InterfaceDecl:
    name: str
    attributes: List[AttributeLine] = field(default_factory=list)
    operations: List[OperationLine] = field(default_factory=list)

@dataclass
class DataTypeDecl:
    name: str
    attributes: List[AttributeLine] = field(default_factory=list)
    operations: List[OperationLine] = field(default_factory=list)

@dataclass
class TemplateDecl:
    name: str
    template_parameters: List[ParameterLine] = field(default_factory=list)
    attributes: List[AttributeLine] = field(default_factory=list)
    operations: List[OperationLine] = field(default_factory=list)

@dataclass
class TemplateBindingDecl:
    bound_element: str
    template: str
    substitutions: List[ParameterLine] = field(default_factory=list)

@dataclass
class EnumDecl:
    name: str
    literals: List[str] = field(default_factory=list)

@dataclass
class GeneralizationDecl:
    specific: str
    general: str
    substitutable: bool = True


@dataclass
class DependencyDecl:
    client: str
    supplier: str
    stereotype: Optional[str] = None


@dataclass
class RealizationDecl:
    implementer: str
    interface: str


@dataclass
class AssocEnd:
    participant: str
    multiplicity: Optional[str] = None
    role: Optional[str] = None


@dataclass
class AssociationDecl:
    end1: AssocEnd
    end2: AssocEnd
    name: Optional[str] = None
    is_derived: bool = False
    aggregation: Optional[str] = None

@dataclass
class AssociationClassDecl:
    name: str
    association: AssociationDecl
    attributes: List[AttributeLine] = field(default_factory=list)
    operations: List[OperationLine] = field(default_factory=list)

@dataclass
class AlignCmd:
    where: str
    elements: List[str]


@dataclass
class DistributeCmd:
    axis: str
    elements: List[str]
    step: Optional[int] = None


@dataclass
class FixCmd:
    element: str
    x: float
    y: float


@dataclass
class BindCmd:
    elem1: str
    direction: str
    elem2: str


LayoutCommand = Union[AlignCmd, DistributeCmd, FixCmd, BindCmd]


@dataclass
class LayoutBlock:
    commands: List[LayoutCommand] = field(default_factory=list)


Declaration = Union[
    ClassDecl,
    InterfaceDecl,
    DataTypeDecl,
    TemplateDecl,
    TemplateBindingDecl,
    EnumDecl,
    GeneralizationDecl,
    DependencyDecl,
    RealizationDecl,
    AssociationDecl,
    AssociationClassDecl,
]


@dataclass
class Document:
    declarations: List[Declaration] = field(default_factory=list)
    layout: Optional[LayoutBlock] = None
