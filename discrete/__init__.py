"""
Прикладной слой: онтология дискретной математики поверх :mod:`ontol`.

- :mod:`discrete.names`   --- словарь имён схемы (единственное место с именами);
- :mod:`discrete.schema`  --- построение схемы в одном из трёх профилей;
- :mod:`discrete.content` --- загрузка контента из TDL-файлов и его валидация;
- :mod:`discrete.journal` --- журнал выдач и попыток студентов (SQLite);
- :mod:`discrete.variants` --- генераторы вариантов задач;
- :mod:`discrete.checking` --- проверка ответов студента запросами к онтологии.

Контент и журнал --- ДВА отдельных хранилища: первое редактируемый справочник
в git, второе событийный поток. Подробности --- ``docs/storage.md``.

Имена элементов онтологии --- на кириллице (это данные), идентификаторы Python
--- на латинице. Зависимость строго в одну сторону:
``discrete`` -> ``ontol`` -> ``uml_dsl``.
"""
import ontol  # бутстрап ядра: кладёт ontol_core/ в sys.path  # noqa: F401

from .checking import (
    CheckError,
    CheckResult,
    Diagnosis,
    check,
    hint,
    parse_diagram_answer,
    parse_number_answer,
    parse_set_answer,
)
from .content import (
    Content,
    ContentError,
    SourceLocation,
    Violation,
    check_invariants,
    content_version,
    discover_files,
    load_content,
)
from .journal import Attempt, Issue, Journal, JournalError, Verdict
from .names import CYRILLIC, VOCABULARY, Vocabulary
from .schema import Profile, build_schema, reference_class
from .variants import (
    GeneratorContext,
    QueryExpectation,
    SubgraphExpectation,
    ValueExpectation,
    Variant,
    VariantError,
    content_units,
    generate,
    generate_many,
    register,
)

__all__ = [
    # имена
    "Vocabulary",
    "CYRILLIC",
    "VOCABULARY",
    # схема
    "Profile",
    "build_schema",
    "reference_class",
    # контент
    "Content",
    "ContentError",
    "SourceLocation",
    "Violation",
    "load_content",
    "check_invariants",
    "discover_files",
    "content_version",
    # журнал
    "Journal",
    "JournalError",
    "Verdict",
    "Attempt",
    "Issue",
    # варианты задач
    "Variant",
    "VariantError",
    "QueryExpectation",
    "ValueExpectation",
    "GeneratorContext",
    "generate",
    "generate_many",
    "register",
    "content_units",
    "SubgraphExpectation",
    # проверка ответов
    "check",
    "hint",
    "CheckResult",
    "CheckError",
    "Diagnosis",
    "parse_set_answer",
    "parse_number_answer",
    "parse_diagram_answer",
]
