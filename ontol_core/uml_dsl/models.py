"""
Базовые модели UML DSL: кратность, атрибуты, операции, параметры, классификаторы.

Все поля и проверки подкреплены цитатами из книги «Моделирование на UML»
(Новиков, Иванов), разделы 3.1–3.3. Используется Pydantic v2.
"""
from __future__ import annotations

import html as html_mod
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

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

# ─── SVG константы стилей ─────────────────────────────────────────────────
SVG_FONT_FAMILY = "Arial"
SVG_FONT_SIZE = 12
SVG_FONT_WEIGHT = 500
SVG_CHAR_WIDTH = 7.2
SVG_LINE_HEIGHT = 16
SVG_PADDING = 8
SVG_MIN_WIDTH = 120
SVG_BADGE_RADIUS = 11
SVG_BADGE_GAP = 8
SVG_BADGE_TEXT_PAD = SVG_BADGE_RADIUS * 2 + SVG_BADGE_GAP
#SVG_STROKE = "#d7a43c"
#SVG_STROKE_WIDTH = 2
#SVG_FILL_TITLE = "url(#Obj_Gradient)"
#SVG_FILL_ATTRS = "url(#Obj_Gradient_2)"
#SVG_FILL_OPS = "url(#Obj_Gradient_3)"

SVG_STROKE = "#999999"
SVG_STROKE_WIDTH = 1
SVG_FILL_TITLE = "#e5e5e5"
SVG_FILL_ATTRS = "#eeeeee"
SVG_FILL_OPS = "#eeeeee"
# ═══════════════════════════════════════════════════════════════════════════
# ModelElement — корень иерархии (§3.3, рис. 3.3)
# ═══════════════════════════════════════════════════════════════════════════

PrimitiveType = Union[str, int, float, bool]


def _svg_data(name: str, value: Any) -> str:
    return f'{name}="{html_mod.escape("" if value is None else str(value), quote=True)}"'


def _svg_bool(value: bool) -> str:
    return "true" if value else "false"


def _svg_optional_bool(value: Optional[bool]) -> str:
    if value is None:
        return ""
    return _svg_bool(value)


def _primitive_kind(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"

# Map textual primitive type names to Python types for validation/normalization
PRIMITIVE_TYPE_MAP: Dict[str, type] = {
    "String": str,
    "str": str,
    "Integer": int,
    "int": int,
    "Float": float,
    "float": float,
    "double": float,
    "Boolean": bool,
    "bool": bool,
}


class ModelElement(BaseModel):
    """Элемент модели — абстрактный корень иерархии UML (§3.3, рис. 3.3).

    Цитата-метамодель: «ModelElement — абстрактный суперкласс, имеющий
    два свойства: name и visibility.»
    """
    name: str = Field(
        ..., min_length=1, max_length=255,
        description="Имя элемента. Цитата: «Имя служит для идентификации элемента модели.»",
    )
    visibility: Optional[Visibility] = Field(
        default=None,
        description=(
            "Видимость элемента (+, -, #, ~). "
            "Цитата: «если видимость не указана, никакого значения по умолчанию "
            "не подразумевается.»"
        ),
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        """Цитата: «Имя служит для идентификации элемента модели.»"""
        if not v.strip():
            raise ValueError("Имя элемента модели не может быть пустым")
        return v.strip()


# ═══════════════════════════════════════════════════════════════════════════
# Feature — составляющая классификатора (§3.9, рис. 3.9)
# ═══════════════════════════════════════════════════════════════════════════


class ClassFeature(ModelElement):
    """Составляющая классификатора (§3.9, рис. 3.9).

    Переименовано в `ClassFeature` чтобы явно отличать от общих понятий.

    Цитата-метамодель: «Feature — абстрактный суперкласс для Attribute
    и Operation. Имеет свойство isStatic : Boolean (scope в UML 1).»

    Поле `redefines` указывает имя элемента (атрибута/операции) родительского
    классификатора, который переопределяется данной составляющей.
    """
    scope: Scope = Field(
        default=Scope.INSTANCE,
        description=(
            "Область действия (instance/classifier). "
            "Метамодель: isStatic : Boolean. "
            "Цитата: «Подчеркивание описания соответствует описателю static.»"
        ),
    )
    redefines: Optional[str] = Field(
        default=None,
        description=(
            "Имя переопределяемого элемента родительского класса (attribute/operation)."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Кратность (Multiplicity)
# ═══════════════════════════════════════════════════════════════════════════


class MultiplicityRange(BaseModel):
    """Один диапазон кратности: lower..upper (§3.1.3).

    Цитата: «Синтаксически кратность задается выражением, каждый элемент
    которого имеет формат: Нижняя граница .. ВЕРХНЯЯ ГРАНИЦА.»

    Цитата: «В качестве верхней и нижней границы используются натуральные
    числа или ноль. Кроме того, в качестве верхней границы может
    использоваться символ *.»

    Цитата (таблица): «5..3 — Некорректная кратность. Нижняя граница больше
    верхней. -1..3 — Некорректная кратность. Отрицательные числа недопустимы.»
    """
    lower: int = Field(
        default=0,
        ge=0,
        description="Нижняя граница (>=0). Цитата: «Отрицательные числа недопустимы.»",
    )
    upper: Optional[int] = Field(
        default=None,
        description="Верхняя граница (>=0) или None для *. Цитата: «символ * (неограниченно)»",
    )

    @model_validator(mode="after")
    def _bounds_consistent(self) -> "MultiplicityRange":
        # Цитата: «5..3 — Некорректная кратность. Нижняя граница больше верхней.»
        if self.upper is not None:
            if self.upper < 0:
                raise ValueError("Верхняя граница кратности не может быть отрицательной")
            if self.lower > self.upper:
                raise ValueError(
                    f"Нижняя граница ({self.lower}) больше верхней ({self.upper})"
                )
        return self

    def __str__(self) -> str:
        up = "*" if self.upper is None else str(self.upper)
        if self.lower == self.upper:
            return str(self.lower)
        return f"{self.lower}..{up}"


class Multiplicity(BaseModel):
    """Кратность — набор диапазонов (§3.1.3).

    Цитата: «Кратность (multiplicity) множества — это множество чисел,
    которые задают все допустимые значения мощности для данного множества.»

    Цитата: «Синтаксически кратность задается выражением, которое является
    непустой последовательностью элементов (разделённых запятыми).»
    Пример: '1..3, 5, 7..10'
    """
    ranges: List[MultiplicityRange] = Field(
        default_factory=lambda: [MultiplicityRange(lower=0, upper=None)],
        description="Список диапазонов кратности. По умолчанию '*' (0..*).",
    )

    def __str__(self) -> str:
        return ", ".join(str(r) for r in self.ranges)


# ═══════════════════════════════════════════════════════════════════════════
# Параметры
# ═══════════════════════════════════════════════════════════════════════════


class Parameter(BaseModel):
    """Параметр операции (§3.2.3).

    Цитата: «направление ПАРАМЕТР : тип = значение»
    Цитата: «in — входной параметр, out — выходной, inout — одновременно,
    return — возвращаемое значение.»
    """
    name: str = Field(
        ..., min_length=1, description="Имя параметра",
    )
    type_: Optional[str] = Field(
        default=None, description="Тип параметра",
    )
    direction: ParamDirection = Field(
        default=ParamDirection.IN,
        description="Направление: in (по умолчанию), out, inout, return.",
    )
    default: Optional[Any] = Field(
        default=None,
        description="Значение по умолчанию для параметра",
    )

    def to_text(self) -> str:
        """Текстовое представление параметра в нотации UML."""
        parts: list[str] = []
        if self.direction != ParamDirection.IN:
            parts.append(self.direction.value)
        parts.append(self.name)
        if self.type_:
            parts.append(f": {self.type_}")
        if self.default is not None:
            parts.append(f" = {self.default}")
        return " ".join(parts)

    @model_validator(mode="after")
    def _validate_default_value(self) -> "Parameter":
        """Validate/normalize `default` when `type_` is a primitive.

        If `type_` names a primitive in PRIMITIVE_TYPE_MAP, attempt to coerce
        `default` to that Python type (unless it's None). Raise ValueError on
        failure. Non-primitive types are validated at diagram-level.
        """
        if not self.type_:
            return self

        expected = PRIMITIVE_TYPE_MAP.get(self.type_)
        if expected and self.default is not None:
            if not isinstance(self.default, expected):
                try:
                    coerced = expected(self.default)
                except Exception:
                    raise ValueError(
                        f"Default value for parameter '{self.name}' cannot be coerced to {self.type_}"
                    )
                object.__setattr__(self, "default", coerced)
        return self


# ═══════════════════════════════════════════════════════════════════════════
# Атрибут
# ═══════════════════════════════════════════════════════════════════════════


class Attribute(ClassFeature):
    """Атрибут класса (§3.2.2). Наследует Feature → ModelElement (§3.9, рис. 3.9).

    Метамодель: Feature → Attribute.
    Наследуемые свойства: name, visibility (от ModelElement), scope (от Feature).

    Цитата: «Атрибут — это именованное место (или, как говорят, слот),
    в котором может храниться значение.»

    Синтаксис: «видимость ИМЯ кратность : тип = начальное_значение {свойства}»
    """
    type_: Optional[str] = Field(
        default=None,
        description="Тип атрибута (String, int и т.п.).",
    )
    multiplicity: Optional[MultiplicityRange] = Field(
        default=None,
        description=(
            "Кратность атрибута. "
            "Цитата: «Если кратность присутствует, атрибут — массив (определённой "
            "или неопределённой длины).»"
        ),
    )
    initial_value: Optional[Any] = Field(
        default=None,
        description=(
            "Начальное значение. "
            "Цитата: «Если начальное значение не указано, никакого значения по "
            "умолчанию не подразумевается.»"
        ),
    )
    changeability: Optional[Changeability] = Field(
        default=None,
        description=(
            "Изменяемость ({changeable}, {readOnly}, {frozen}, {addOnly}). "
            "Цитата: «Свойство {readOnly} означает, что значение не может быть "
            "изменено после инициализации.»"
        ),
    )

    def to_text(self) -> str:
        """Текстовое представление атрибута в нотации UML."""
        parts: list[str] = []
        if self.visibility:
            parts.append(self.visibility.value)
        parts.append(self.name)
        if self.multiplicity and str(self.multiplicity) not in ("0..*", "*"):
            parts.append(f"[{self.multiplicity}]")
        if self.type_:
            parts.append(f": {self.type_}")
        if self.initial_value is not None:
            parts.append(f"= {self.initial_value}")
        if self.changeability:
            parts.append(f"{{{self.changeability.value}}}")
        # redefines was removed from Attribute; redefinition is represented
        # at the role/association or operation level elsewhere.
        return " ".join(parts)

    @model_validator(mode="after")
    def _validate_initial_value(self) -> "Attribute":
        """Validate/normalize `initial_value` when `type_` is a primitive.

        - If `type_` names a primitive in PRIMITIVE_TYPE_MAP, attempt to
          coerce `initial_value` to that Python type (unless it's None).
        - If coercion fails, raise ValueError.

        Note: validation that `type_` names an existing `Class` on the
        diagram must be performed at the diagram/graph level where all
        classifiers are known.
        """
        if not self.type_:
            return self

        expected = PRIMITIVE_TYPE_MAP.get(self.type_)
        if expected:
            if self.initial_value is None:
                return self
            # If already the right type, accept; otherwise try to coerce.
            if not isinstance(self.initial_value, expected):
                try:
                    coerced = expected(self.initial_value)
                except Exception:
                    raise ValueError(
                        f"Initial value for attribute '{self.name}' cannot be coerced to {self.type_}"
                    )
                # assign normalized value
                object.__setattr__(self, "initial_value", coerced)
        # non-primitive types: defer structural validation to diagram-level
        return self


# ═══════════════════════════════════════════════════════════════════════════
# Операция
# ═══════════════════════════════════════════════════════════════════════════


class Operation(ClassFeature):
    """Операция (метод) классификатора (§3.2.3). Наследует Feature → ModelElement (§3.9, рис. 3.9).

    Метамодель: Feature → Operation.
    Наследуемые свойства: name, visibility (от ModelElement), scope (от Feature).

    Цитата: «Операция — это спецификация действия с объектом: изменение
    значения его атрибутов, вычисление нового значения и т.д.»

    Синтаксис: «видимость ИМЯ (параметры) : тип {свойства}»

    Цитата: «Метод — это реализация операции, т.е. выполняемый алгоритм.»
    """
    parameters: List[Parameter] = Field(
        default_factory=list,
        description="Параметры операции.",
    )
    return_type: Optional[str] = Field(
        default=None,
        description="Тип возвращаемого значения.",
    )
    is_abstract: bool = Field(
        default=False,
        description=(
            "Абстрактная операция (записывается курсивом). "
            "Цитата: «Абстрактная операция не имеет метода в этом классе.»"
        ),
    )
    is_query: bool = Field(
        default=False,
        description=(
            "Операция без побочных эффектов. "
            "Цитата: «{isQuery} = true → операция не имеет побочных эффектов (чистая функция/запрос).»"
        ),
    )
    concurrency: Concurrency = Field(
        default=Concurrency.SEQUENTIAL,
        description=(
            "Параллелизм: sequential (по умолч.), guarded, concurrent. "
            "Цитата: «{sequential} — не допускает параллельных вызовов.»"
        ),
    )
    is_leaf: bool = Field(
        default=False,
        description=(
            "Не может быть переопределена в подклассах. "
            "Цитата: «{leaf} → реализация операции не должна быть переопределяема "
            "в подклассах.»"
        ),
    )

    def signature(self) -> Tuple[str, Tuple[Optional[str], ...]]:
        """Сигнатура операции.

        Цитата: «Сигнатура — имя + число, порядок и типы параметров.
        Направление, имена параметров и тип возвращаемого значения НЕ входят
        в сигнатуру.»

        Цитата: «В одном классе не может быть двух операций с одной
        сигнатурой — модель считается противоречивой.»
        """
        return (
            self.name,
            tuple(
                p.type_
                for p in self.parameters
                if p.direction != ParamDirection.RETURN
            ),
        )

    def to_text(self) -> str:
        """Текстовое представление операции в нотации UML."""
        parts: list[str] = []
        if self.visibility:
            parts.append(self.visibility.value)
        params_text = ", ".join(p.to_text() for p in self.parameters)
        parts.append(f"{self.name}({params_text})")
        if self.return_type:
            parts.append(f": {self.return_type}")
        props: list[str] = []
        if self.is_query:
            props.append("isQuery")
        if self.is_leaf:
            props.append("leaf")
        if self.concurrency != Concurrency.SEQUENTIAL:
            props.append(self.concurrency.value)
        if props:
            parts.append("{" + ", ".join(props) + "}")
        # 'redefines' was removed from Operation; redefinition is represented
        # at the role/association or attribute level elsewhere.
        return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Помеченное значение
# ═══════════════════════════════════════════════════════════════════════════


class TaggedValue(BaseModel):
    """Помеченное значение (tagged value) (§3.2.1).

    Цитата: «{свойства} — пары имя=значение, разделённые запятыми.»
    """
    name: str = Field(..., min_length=1)
    value: Optional[PrimitiveType] = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════════
# Шаблон (Template)
# ═══════════════════════════════════════════════════════════════════════════


class TemplateParameter(BaseModel):
    """Параметр шаблона (§3.2.5).

    Цитата: «Шаблон — это сущность (чаще всего классификатор) с параметрами.»
    Цитата: «Параметром может быть любой элемент описания классификатора
    (тип составляющей, кратность атрибута и т.п.)»
    """
    name: str = Field(..., min_length=1)
    type_: Optional[str] = Field(default=None)
    default_value: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════════
# Классификатор (Classifier) — основная сущность
# ═══════════════════════════════════════════════════════════════════════════


class Classifier(ModelElement):
    """Классификатор — дескриптор множества однотипных объектов (§3.1.3).
    Наследует ModelElement (§3.3, рис. 3.3): name, visibility.

    Цитата-метамодель: «Classifier — подкласс ModelElement. Содержит
    составляющие (Feature): атрибуты и операции (композиция 1 → *).»

    Цитата: «Классификатор (classifier) — это дескриптор множества однотипных объектов.»

    Семь основных свойств (§3.1.3):
    1) Имя — «Имя служит для идентификации элемента модели.»
    2) Экземпляры — «Классификатор может иметь экземпляры (прямые и косвенные).»
    3) Абстрактность — «Абстрактный классификатор не может иметь прямых экземпляров.»
    4) Видимость — «Видимость определяет, может ли составляющая использоваться.»
    5) Область действия — «Область действия определяет, как проявляет себя составляющая.»
    6) Кратность — «Классификатор имеет кратность.»
    7) Обобщение — «Классификаторы (и только они!) могут участвовать в отношении обобщения.»
    """
    multiplicity: Optional[Multiplicity] = Field(
        default=None,
        description=(
            "Кратность классификатора. "
            "Цитата: «Классификатор имеет произвольное число экземпляров (кратность *). "
            "Поскольку этот вариант встречается чаще всего, он подразумевается по умолчанию.»"
        ),
    )

    # В текущей модели `Classifier` — более абстрактный концепт (§3.1).
    # Специфичные для визуализации и семантики поля (attributes, operations,
    # tagged_values и т.п.) вынесены в подкласс `Class`.

    # Текстовое/визуальное представление классов вынесено в подкласс `Class`.


# ──────────────────────────────────────────────────────────────────────────
# Class — конкретный класс UML (§3.2)
# ──────────────────────────────────────────────────────────────────────────


class Class(Classifier):
    """Класс (Class) — конкретный вид классификатора, соответствующий разделу §3.2.

    В `Class` вынесены поля, специфичные для классов: `stereotype`,
    `is_abstract`, `attributes`, `operations`, `tagged_values`.
    """
    stereotype: Optional[Stereotype] = Field(
        default=None,
        description=(
            "Стереотип класса. "
            "Цитата: «Для классов определены стандартные стереотипы.»"
        ),
    )
    is_abstract: bool = Field(
        default=False,
        description=(
            "Абстрактный класс (имя курсивом). "
            "Цитата: «Абстрактный классификатор не может иметь прямых экземпляров "
            "и в этом случае его имя выделяется курсивом.»"
        ),
    )
    attributes: List[Attribute] = Field(
        default_factory=list,
        description="Атрибуты (секция атрибутов).",
    )
    operations: List[Operation] = Field(
        default_factory=list,
        description="Операции (секция операций).",
    )
    tagged_values: List[TaggedValue] = Field(
        default_factory=list,
        description="Помеченные значения.",
    )

    @model_validator(mode="after")
    def _interface_all_abstract(self) -> "Class":
        if self.stereotype == Stereotype.INTERFACE:
            for op in self.operations:
                if not op.is_abstract:
                    raise ValueError(
                        f"Операция '{op.name}' интерфейса '{self.name}' должна быть абстрактной"
                    )
        return self

    @model_validator(mode="after")
    def _utility_no_instances(self) -> "Class":
        if self.stereotype == Stereotype.UTILITY:
            for attr in self.attributes:
                if attr.scope != Scope.CLASSIFIER:
                    raise ValueError(
                        f"Атрибут '{attr.name}' службы '{self.name}' должен иметь scope=classifier"
                    )
            for op in self.operations:
                if op.scope != Scope.CLASSIFIER:
                    raise ValueError(
                        f"Операция '{op.name}' службы '{self.name}' должна иметь scope=classifier"
                    )
        return self

    @model_validator(mode="after")
    def _unique_operation_signatures(self) -> "Class":
        seen: Dict[Tuple[str, Tuple[Optional[str], ...]], str] = {}
        for op in self.operations:
            sig = op.signature()
            if sig in seen:
                raise ValueError(
                    f"Дублирование сигнатуры операции '{op.name}' в классе '{self.name}'"
                )
            seen[sig] = op.name
        return self

    @model_validator(mode="after")
    def _data_type_ops_constraints(self) -> "Class":
        if self.stereotype in (Stereotype.DATA_TYPE, Stereotype.ENUMERATION):
            for op in self.operations:
                if not op.is_query:
                    raise ValueError(
                        f"Операция '{op.name}' типа данных '{self.name}' должна быть isQuery"
                    )
                if op.scope != Scope.CLASSIFIER:
                    raise ValueError(
                        f"Операция '{op.name}' типа данных '{self.name}' должна иметь scope=classifier"
                    )
        return self

    # Текстовое и SVG-представления перенесены в Class
    def to_text(self) -> str:
        lines: list[str] = []
        header = ""
        if self.stereotype:
            header += f"«{self.stereotype.value}» "
        header += self.name
        if self.is_abstract:
            header += " {abstract}"
        if self.multiplicity:
            header += f" {self.multiplicity}"
        lines.append(header)
        lines.append("---")
        for a in self.attributes:
            lines.append(a.to_text())
        lines.append("---")
        for o in self.operations:
            lines.append(o.to_text())
        return "\n".join(lines)

    def _measure_text_width(self, text: str) -> float:
        return len(text) * SVG_CHAR_WIDTH

    def _feature_display_text(self, text: str) -> str:
        if text.startswith(("+ ", "- ", "# ", "~ ")):
            return text[2:]
        return text

    def to_svg(self, x: float = 0.0, y: float = 0.0, class_id: Optional[str] = None, is_instance: bool = False) -> str:
        if self.stereotype == Stereotype.ENUMERATION:
            return self._enum_to_svg(x=x, y=y, class_id=class_id)

        esc = html_mod.escape
        p = SVG_PADDING
        lh = SVG_LINE_HEIGHT
        fs = SVG_FONT_SIZE

        title_lines: list[str] = []
        if self.stereotype:
            title_lines.append(f"«{self.stereotype.value}»")
        title_lines.append(self.name)
        if self.multiplicity:
            title_lines.append(str(self.multiplicity))

        attr_lines = [a.to_text() for a in self.attributes]
        op_lines = [o.to_text() for o in self.operations]

        # template parameters may exist only on Template instances
        tpl_params = getattr(self, "template_parameters", []) or []
        tpl_h = 0
        tpl_w = 0
        tpl_text = ""
        if tpl_params:
            tpl_text = ", ".join((tp.name + (f": {tp.type_}" if tp.type_ else "")) for tp in tpl_params)
            tpl_w = self._measure_text_width(tpl_text) + p * 2
            tpl_h = lh + p

        if self.stereotype == Stereotype.INTERFACE:
            class_kind = "interface"
            badge_kind = "I"
        elif self.stereotype == Stereotype.DATA_TYPE:
            class_kind = "dataType"
            badge_kind = "D"
        else:
            class_kind = "template" if tpl_params else "class"
            badge_kind = "C"

        title_text_w = max((self._measure_text_width(l) for l in title_lines), default=0)
        body_text_w = max((self._measure_text_width(self._feature_display_text(l)) for l in attr_lines + op_lines), default=0)
        width = max(
            SVG_MIN_WIDTH,
            title_text_w + p * 2 + SVG_BADGE_TEXT_PAD + 4,
            body_text_w + p * 2 + 18,
        )

        title_h = p * 2 + lh * len(title_lines)
        attrs_h = (p * 2 + lh * len(attr_lines)) if attr_lines else 0
        ops_h = (p * 2 + lh * len(op_lines)) if op_lines else 0
        total_h = title_h + attrs_h + ops_h

        cid = class_id or self.name.replace(" ", "_")
        gx, gy = int(x), int(y)

        parts: list[str] = []
        # Формируем data-атрибуты для обратного парсинга
        data_attrs = [
            _svg_data("data-id", cid),
            _svg_data("data-name", self.name),
            f'data-type="class"',
            _svg_data("data-class-kind", class_kind),
            _svg_data("data-visibility", self.visibility.value if self.visibility else ""),
            _svg_data("data-stereotype", self.stereotype.value if self.stereotype else ""),
            _svg_data("data-abstract", _svg_bool(self.is_abstract)),
            _svg_data("data-multiplicity", str(self.multiplicity) if self.multiplicity else ""),
            _svg_data("data-attributes-count", len(self.attributes)),
            _svg_data("data-operations-count", len(self.operations)),
            _svg_data("data-tagged-values-count", len(self.tagged_values)),
            _svg_data("data-template-parameters-count", len(tpl_params)),
        ]

        parts.append(f'<g transform="translate({gx},{gy})" class="uml-class" {" ".join(data_attrs)}>')

        for i, tagged_value in enumerate(self.tagged_values):
            value = tagged_value.value
            parts.append(
                '<metadata '
                'data-type="tagged-value" '
                f'{_svg_data("data-index", i)} '
                f'{_svg_data("data-name", tagged_value.name)} '
                f'{_svg_data("data-has-value", _svg_bool(value is not None))} '
                f'{_svg_data("data-value-kind", _primitive_kind(value))} '
                f'{_svg_data("data-value", "" if value is None else value)}'
                '/>'
            )

        for i, template_parameter in enumerate(tpl_params):
            parts.append(
                '<metadata '
                'data-type="template-parameter" '
                f'{_svg_data("data-index", i)} '
                f'{_svg_data("data-name", template_parameter.name)} '
                f'{_svg_data("data-parameter-type", template_parameter.type_ or "")} '
                f'{_svg_data("data-has-default-value", _svg_bool(template_parameter.default_value is not None))} '
                f'{_svg_data("data-default-value", template_parameter.default_value or "")}'
                '/>'
            )

        parts.append(f'<rect class="uml-class-title" x="0" y="0" width="{width}" height="{title_h}" fill="{SVG_FILL_TITLE}"/>')
        parts.append(f'<rect class="uml-class-outline uml-class-title-outline" x="0" y="0" width="{width}" height="{title_h}" stroke="{SVG_STROKE}" stroke-width="{SVG_STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>')

        badge_x = p + SVG_BADGE_RADIUS
        badge_y = title_h / 2
        parts.append(self._render_kind_badge(badge_x, badge_y, badge_kind))
        title_text_x = badge_x + SVG_BADGE_RADIUS + SVG_BADGE_GAP

        for i, line in enumerate(title_lines):
            ty = p + fs + i * lh
            font_style = ' font-style="italic"' if self.is_abstract and line == self.name else ""
            # Add underline for instance names (clients in INSTANCE_OF dependencies)
            text_decor = ' text-decoration="underline"' if is_instance and line == self.name else ""
            parts.append(f'<text class="uml-class-title-text" x="{title_text_x}" y="{ty}" text-anchor="start"{font_style}{text_decor} fill="black" font-family="{SVG_FONT_FAMILY}" font-size="{fs}" font-weight="{SVG_FONT_WEIGHT}">{esc(line)}</text>')

        if attr_lines:
            ay = title_h
            parts.append(f'<rect class="uml-class-section uml-class-attributes-section" x="0" y="{ay}" width="{width}" height="{attrs_h}" fill="{SVG_FILL_ATTRS}"/>')
            parts.append(f'<rect class="uml-class-outline uml-class-section-outline" x="0" y="{ay}" width="{width}" height="{attrs_h}" stroke="{SVG_STROKE}" stroke-width="{SVG_STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>')
            for i, line in enumerate(attr_lines):
                ty = ay + p + fs + i * lh
                decor = ''
                attr = self.attributes[i]
                if attr.scope == Scope.CLASSIFIER:
                    decor = ' text-decoration="underline"'
                attr_data = [
                    'data-type="attribute"',
                    _svg_data("data-index", i),
                    _svg_data("data-name", attr.name),
                    _svg_data("data-visibility", attr.visibility.value if attr.visibility else ""),
                    _svg_data("data-scope", attr.scope.value),
                    _svg_data("data-value-type", attr.type_ or ""),
                    _svg_data("data-multiplicity", str(attr.multiplicity) if attr.multiplicity else ""),
                    _svg_data("data-has-initial-value", _svg_bool(attr.initial_value is not None)),
                    _svg_data("data-initial-value-kind", _primitive_kind(attr.initial_value)),
                    _svg_data("data-initial-value", "" if attr.initial_value is None else attr.initial_value),
                    _svg_data("data-changeability", attr.changeability.value if attr.changeability else ""),
                    _svg_data("data-redefines", attr.redefines or ""),
                ]
                parts.append(f'<g class="uml-feature uml-attribute" {" ".join(attr_data)}>')
                parts.append(f'<circle class="uml-feature-bullet uml-attribute-bullet" cx="{p + 4}" cy="{ty - 4}" r="3" fill="white" stroke="#3aa76d" stroke-width="1.3"/>')
                parts.append(f'<text class="uml-feature-text uml-attribute-text" x="{p + 14}" y="{ty}" fill="black"{decor} font-family="{SVG_FONT_FAMILY}" font-size="{fs}" font-weight="{SVG_FONT_WEIGHT}">{esc(self._feature_display_text(line))}</text>')
                parts.append('</g>')

        if op_lines:
            oy = title_h + attrs_h
            parts.append(f'<rect class="uml-class-section uml-class-operations-section" x="0" y="{oy}" width="{width}" height="{ops_h}" fill="{SVG_FILL_OPS}"/>')
            parts.append(f'<rect class="uml-class-outline uml-class-section-outline" x="0" y="{oy}" width="{width}" height="{ops_h}" stroke="{SVG_STROKE}" stroke-width="{SVG_STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>')
            for i, line in enumerate(op_lines):
                ty = oy + p + fs + i * lh
                op = self.operations[i]
                font_style = ' font-style="italic"' if op.is_abstract else ''
                decor = ' text-decoration="underline"' if op.scope == Scope.CLASSIFIER else ''
                op_data = [
                    'data-type="operation"',
                    _svg_data("data-index", i),
                    _svg_data("data-name", op.name),
                    _svg_data("data-visibility", op.visibility.value if op.visibility else ""),
                    _svg_data("data-scope", op.scope.value),
                    _svg_data("data-return-type", op.return_type or ""),
                    _svg_data("data-abstract", _svg_bool(op.is_abstract)),
                    _svg_data("data-query", _svg_bool(op.is_query)),
                    _svg_data("data-leaf", _svg_bool(op.is_leaf)),
                    _svg_data("data-concurrency", op.concurrency.value),
                    _svg_data("data-redefines", op.redefines or ""),
                    _svg_data("data-parameters-count", len(op.parameters)),
                ]
                parts.append(f'<g class="uml-feature uml-operation" {" ".join(op_data)}>')
                for param_index, param in enumerate(op.parameters):
                    parts.append(
                        '<metadata '
                        'data-type="operation-parameter" '
                        f'{_svg_data("data-index", param_index)} '
                        f'{_svg_data("data-name", param.name)} '
                        f'{_svg_data("data-parameter-type", param.type_ or "")} '
                        f'{_svg_data("data-direction", param.direction.value)} '
                        f'{_svg_data("data-has-default", _svg_bool(param.default is not None))} '
                        f'{_svg_data("data-default-kind", _primitive_kind(param.default))} '
                        f'{_svg_data("data-default", "" if param.default is None else param.default)}'
                        '/>'
                    )
                parts.append(f'<circle class="uml-feature-bullet uml-operation-bullet" cx="{p + 4}" cy="{ty - 4}" r="3" fill="#3aa76d" stroke="#2a7d50" stroke-width="1"/>')
                parts.append(f'<text class="uml-feature-text uml-operation-text" x="{p + 14}" y="{ty}" fill="black"{font_style}{decor} font-family="{SVG_FONT_FAMILY}" font-size="{fs}" font-weight="{SVG_FONT_WEIGHT}">{esc(self._feature_display_text(line))}</text>')
                parts.append('</g>')

        if tpl_params:
            tx = width - tpl_w / 2
            _ty = -tpl_h / 2
            parts.append(f'<rect class="uml-template-box" x="{tx}" y="{_ty}" width="{tpl_w}" height="{tpl_h}" fill="white" stroke="{SVG_STROKE}" stroke-dasharray="4,3" stroke-width="1"/>')
            parts.append(f'<text class="uml-template-text" x="{tx + p}" y="{_ty + fs + 2}" fill="black" font-family="{SVG_FONT_FAMILY}" font-size="{fs}" font-weight="{SVG_FONT_WEIGHT}">{esc(tpl_text)}</text>')

        parts.append(f'<rect class="uml-bbox" x="0" y="0" width="{width}" height="{total_h}" fill="none" stroke="none" pointer-events="all"/>')
        parts.append("</g>")
        return "\n".join(parts)

    def _render_kind_badge(self, x: float, y: float, kind: str) -> str:
        if kind == "E":
            fill = "#f29b86"
            stroke = "#9d3f2f"
        elif kind == "I":
            fill = "#c9d7ff"
            stroke = "#4a61a8"
        elif kind == "D":
            fill = "#d9c7f2"
            stroke = "#6f4aa8"
        else:
            fill = "#b8d9bf"
            stroke = "#3e7d4a"

        return (
            f'<circle class="uml-kind-badge uml-kind-badge-{kind.lower()}" cx="{x}" cy="{y}" r="{SVG_BADGE_RADIUS}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            f'<text class="uml-kind-badge-text" x="{x}" y="{y + 4}" text-anchor="middle" '
            f'font-family="{SVG_FONT_FAMILY}" font-size="12" '
            f'font-weight="700" fill="black">{kind}</text>'
        )
    def get_box_size(self) -> Tuple[float, float]:
        p = SVG_PADDING
        lh = SVG_LINE_HEIGHT

        title_cnt = 1 + (1 if self.stereotype else 0) + (1 if self.multiplicity else 0)
        title_lines_strs: list[str] = []
        if self.stereotype:
            title_lines_strs.append(f"«{self.stereotype.value}»")
        title_lines_strs.append(self.name)
        if self.multiplicity:
            title_lines_strs.append(str(self.multiplicity))
        attr_strs = [a.to_text() for a in self.attributes]
        op_strs = [o.to_text() for o in self.operations]
        title_w = max((self._measure_text_width(s) for s in title_lines_strs), default=0)
        body_w = max((self._measure_text_width(self._feature_display_text(s)) for s in attr_strs + op_strs), default=0)
        width = max(
            SVG_MIN_WIDTH,
            title_w + p * 2 + SVG_BADGE_TEXT_PAD + 4,
            body_w + p * 2 + 18,
        )

        title_h = p * 2 + lh * title_cnt
        attrs_h = (p * 2 + lh * len(self.attributes)) if self.attributes else 0
        ops_h = (p * 2 + lh * len(self.operations)) if self.operations else 0
        return width, title_h + attrs_h + ops_h

    def _enum_to_svg(self, x: float = 0.0, y: float = 0.0, class_id: Optional[str] = None) -> str:
        esc = html_mod.escape
        p = SVG_PADDING
        lh = SVG_LINE_HEIGHT
        fs = SVG_FONT_SIZE

        values = [a.name for a in self.attributes]

        title_text = self.name
        value_lines = values

        title_w = self._measure_text_width(title_text) + p * 2 + SVG_BADGE_TEXT_PAD + 4
        values_w = max((self._measure_text_width(v) for v in value_lines), default=0) + p * 2 + 4
        width = max(SVG_MIN_WIDTH, title_w, values_w)
        title_h = p * 2 + lh
        values_h = p * 2 + lh * len(value_lines)
        total_h = title_h + values_h

        cid = class_id or self.name.replace(" ", "_")
        gx, gy = int(x), int(y)

        parts: list[str] = []
        parts.append(
            f'<g transform="translate({gx},{gy})" class="uml-class" '
            f'{_svg_data("data-id", cid)} '
            f'{_svg_data("data-name", self.name)} '
            f'data-type="class" '
            f'data-class-kind="class" '
            f'{_svg_data("data-visibility", self.visibility.value if self.visibility else "")} '
            f'data-stereotype="enumeration" '
            f'data-abstract="false" '
            f'{_svg_data("data-multiplicity", str(self.multiplicity) if self.multiplicity else "")} '
            f'{_svg_data("data-attributes-count", len(self.attributes))} '
            f'data-operations-count="0" '
            f'{_svg_data("data-tagged-values-count", len(self.tagged_values))} '
            f'data-template-parameters-count="0">'
        )

        for i, tagged_value in enumerate(self.tagged_values):
            value = tagged_value.value
            parts.append(
                '<metadata '
                'data-type="tagged-value" '
                f'{_svg_data("data-index", i)} '
                f'{_svg_data("data-name", tagged_value.name)} '
                f'{_svg_data("data-has-value", _svg_bool(value is not None))} '
                f'{_svg_data("data-value-kind", _primitive_kind(value))} '
                f'{_svg_data("data-value", "" if value is None else value)}'
                '/>'
            )

        parts.append(
            f'<rect class="uml-class-section uml-enum-body" x="0" y="0" width="{width}" height="{total_h}" fill="#eeeeee" stroke="#999999" stroke-width="1"/>')
        parts.append(
            f'<rect class="uml-class-title uml-enum-title" x="0" y="0" width="{width}" height="{title_h}" fill="#e5e5e5" stroke="#999999" stroke-width="1"/>')

        badge_x = p + SVG_BADGE_RADIUS
        badge_y = title_h / 2
        parts.append(self._render_kind_badge(badge_x, badge_y, "E"))

        parts.append(
            f'<text class="uml-class-title-text uml-enum-title-text" x="{badge_x + 18}" y="{p + fs}" '
            f'font-family="{SVG_FONT_FAMILY}" font-size="{fs}" '
            f'font-weight="700" fill="black">{esc(title_text)}</text>'
        )

        value_y = title_h + p + fs
        for i, value in enumerate(value_lines):
            ty = value_y + i * lh
            parts.append(
                f'<text class="uml-feature-text uml-enum-value-text" '
                f'data-type="enum-literal" '
                f'{_svg_data("data-index", i)} '
                f'{_svg_data("data-name", value)} '
                f'x="{p}" y="{ty}" '
                f'font-family="{SVG_FONT_FAMILY}" font-size="{fs}" '
                f'fill="black">{esc(value)}</text>'
            )

        parts.append(
            f'<rect class="uml-bbox" x="0" y="0" width="{width}" height="{total_h}" fill="none" stroke="none" pointer-events="all"/>')
        parts.append("</g>")

        return "\n".join(parts)

# ──────────────────────────────────────────────────────────────────────────
# Interface — интерфейс UML (§3.2.4)
# ──────────────────────────────────────────────────────────────────────────


class Interface(Class):
    """Interface — специальный классификатор с контрактом операций и атрибутов.

    В учебнике интерфейс описан как абстрактный класс, у которого все
    составляющие являются абстрактными. Поэтому объект хранится как `Class`
    со стереотипом `interface`, но имеет отдельный Python-тип для TDL и
    обратной ретрансляции SVG в модель.
    """
    stereotype: Stereotype = Field(
        default=Stereotype.INTERFACE,
        description="Фиксированный стереотип интерфейса.",
    )
    is_abstract: bool = Field(
        default=True,
        description="Интерфейс не имеет непосредственных экземпляров.",
    )

    @model_validator(mode="before")
    @classmethod
    def _force_interface_data(cls, data):
        if not isinstance(data, dict):
            return data

        data = dict(data)
        data["stereotype"] = Stereotype.INTERFACE
        data["is_abstract"] = True

        operations = []
        for operation in data.get("operations") or []:
            if isinstance(operation, Operation):
                operations.append(operation.model_copy(update={"is_abstract": True}))
            elif isinstance(operation, dict):
                patched = dict(operation)
                patched["is_abstract"] = True
                operations.append(patched)
            else:
                operations.append(operation)
        data["operations"] = operations
        return data


# ──────────────────────────────────────────────────────────────────────────
# DataType — тип данных UML (§3.2.4)
# ──────────────────────────────────────────────────────────────────────────


class DataType(Class):
    """DataType — классификатор значений без объектной идентичности.

    В отличие от класса, тип данных описывает множество значений и операции
    над ними. В текущей модели он хранится как `Class` со стереотипом
    `dataType`, но имеет отдельный Python-тип для TDL и SVG roundtrip.
    """
    stereotype: Stereotype = Field(
        default=Stereotype.DATA_TYPE,
        description="Фиксированный стереотип типа данных.",
    )

    @model_validator(mode="before")
    @classmethod
    def _force_data_type_data(cls, data):
        if not isinstance(data, dict):
            return data

        data = dict(data)
        data["stereotype"] = Stereotype.DATA_TYPE

        operations = []
        for operation in data.get("operations") or []:
            updates = {"is_query": True, "scope": Scope.CLASSIFIER}
            if isinstance(operation, Operation):
                operations.append(operation.model_copy(update=updates))
            elif isinstance(operation, dict):
                patched = dict(operation)
                patched.update(updates)
                operations.append(patched)
            else:
                operations.append(operation)
        data["operations"] = operations
        return data


# ──────────────────────────────────────────────────────────────────────────
# Template — параметризованный класс (шаблон)
# ──────────────────────────────────────────────────────────────────────────


class Template(Class):
    """Template — параметризованный `Class`.

    Стереотип фиксирован как `template` и доступны `template_parameters`.
    """
    # Template не использует отдельный стереотип в перечислении —
    # параметры шаблона хранятся здесь.
    template_parameters: List[TemplateParameter] = Field(
        default_factory=list,
        description=(
            "Параметры шаблона (§3.2.5)."
        ),
    )
