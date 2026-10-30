"""
Словарь имён схемы онтологии дискретной математики.

ЕДИНСТВЕННОЕ место, где зафиксированы имена классов, ролей ассоциаций и слотов.
Прикладной код обязан брать имена отсюда, а не писать строковыми литералами:
имена попадают и в TDL-файлы контента, и в тексты запросов (``@meta=Понятие``,
``требует+``), поэтому разнесённые по коду литералы сделали бы переименование
невыполнимым.

Разделение языков строгое:

- ИМЕНА (значения полей словаря) --- на кириллице: это данные, они видны
  преподавателю в TDL и попадают в текст запроса;
- ИДЕНТИФИКАТОРЫ Python (поля, функции, классы) --- на латинице: они часть
  программного интерфейса и соседствуют с именами из ядра ``uml_dsl``.

Благодаря этому словарь работает именно как слой перевода: перевод онтологии на
латиницу меняет ТОЛЬКО значения --- ``unit="ContentUnit"`` вместо
``unit="ЕдиницаКонтента"``, --- а код, запросы и тесты остаются без правок.

Соглашение об именах: каждое имя --- ОДИН идентификатор (буквы, цифры, ``_``).
Это требование лексера паттернов запросов и лексера TDL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields

#: Допустимое имя: один идентификатор без пробелов, дефисов и точек.
IDENTIFIER = re.compile(r"^\w+$", re.UNICODE)


@dataclass(frozen=True)
class Vocabulary:
    """
    Имена элементов схемы на одном языке.

    Поля сгруппированы по роли: классы, роли ассоциаций (они же метки рёбер в
    запросах), слоты (атрибуты классов). Все значения обязаны быть одиночными
    идентификаторами --- проверяется в :meth:`validate`.
    """

    # классы: содержание
    unit: str
    concept: str
    definition: str
    statement: str
    theorem: str
    lemma: str
    proof: str
    proof_step: str

    # классы: организация курса
    course: str
    topic: str

    # классы: задачи 
    task: str
    variant: str

    # классы-перечисления
    difficulty_level: str
    answer_kind: str

    # роли ассоциаций (метки рёбер в запросах)
    role_defines: str
    role_requires: str
    role_proves: str
    role_justified_by: str
    role_next: str
    role_checks: str

    # слоты
    slot_code: str
    slot_level: str
    slot_text: str
    slot_kind: str
    slot_method: str
    slot_number: str
    slot_term: str
    slot_generator: str
    slot_seed: str
    slot_expected: str

    def validate(self) -> None:
        """
        Убедиться, что все имена --- одиночные идентификаторы и не дублируются.

        :raises ValueError: имя содержит недопустимые символы либо повторяется
        """
        seen: dict = {}
        for field in fields(self):
            name = getattr(self, field.name)
            if not IDENTIFIER.match(name):
                raise ValueError(
                    f"Имя {name!r} (поле {field.name}) не является одиночным "
                    f"идентификатором: пробелы, дефисы и точки недопустимы, "
                    f"иначе имя не запишется в TDL и не адресуется запросом"
                )
            if name in seen:
                raise ValueError(
                    f"Имя {name!r} занято дважды: поля {seen[name]} и {field.name}"
                )
            seen[name] = field.name


#: Словарь схемы на кириллице --- используется по умолчанию.
CYRILLIC = Vocabulary(
    unit="ЕдиницаКонтента",
    concept="Понятие",
    definition="Определение",
    statement="Утверждение",
    theorem="Теорема",
    lemma="Лемма",
    proof="Доказательство",
    proof_step="ШагДоказательства",
    course="Курс",
    topic="Тема",
    task="Задача",
    variant="Вариант",
    difficulty_level="УровеньСложности",
    answer_kind="ВидОтвета",
    role_defines="определяет",
    role_requires="требует",
    role_proves="доказывает",
    role_justified_by="обосновано",
    role_next="далее",
    role_checks="проверяет",
    slot_code="код",
    slot_level="уровень",
    slot_text="формулировка",
    slot_kind="вид",
    slot_method="метод",
    slot_number="номер",
    slot_term="семестр",
    slot_generator="генератор",
    slot_seed="сид",
    slot_expected="эталон",
)

#: Действующий словарь схемы. Перевод онтологии на латиницу --- подмена этой
#: константы вторым словарём с латинскими ЗНАЧЕНИЯМИ; код не меняется.
VOCABULARY = CYRILLIC
