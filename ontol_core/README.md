# ontol_v3_students — UML DSL (TDL ↔ SVG)

Система для работы с UML-диаграммами классов: текстовый язык **TDL** компилируется в
детерминированный **SVG** через Graphviz, SVG парсится обратно в Pydantic-модели, а
диаграммы проходят семантическую валидацию. Есть веб-интерфейс на Streamlit.

**Технологии:** Python 3.10+, Pydantic v2, Graphviz, Streamlit.
**Контекст:** курс «Онтологическое моделирование» (ГА 2026). Данный каталог `ontol_v3/`
— ядро; поверх него построен интерпретатор CIAO (см. `../ciao/`).

## Возможности

- **TDL → SVG** — текстовое описание диаграммы, автоматическая раскладка Graphviz,
  детерминированный результат (одинаковый вход → одинаковый вывод).
- **SVG → модель** — обратный парсинг по `data-*`-атрибутам в Pydantic-модели.
- **Семантическая валидация** — циклы наследования, конфликты множественного
  наследования, ссылочная целостность, корректность типов и кратностей.
- **Экспорт** — SVG, а также PNG/JPG (через CairoSVG/Pillow).
- **Интерфейсы** — командная строка и Streamlit-приложение (2 вкладки).

## Быстрый старт

Команды выполняются из каталога `ontol_v3/`; зависимости — в общем `../requirements.txt`.

```bash
pip install -r ../requirements.txt

# TDL → SVG
python -m uml_dsl.tdl_run examples/example.tdl

# веб-интерфейс (вкладки «Рендер TDL» и «Валидатор SVG»)
streamlit run uml_dsl/app.py

# генерация тестовых SVG и проверка обратного парсинга
cd examples
python -m imported_examples
python -m test_parser
```

Нужен системный **Graphviz** (`dot` в PATH) — им выполняется раскладка.

## Архитектура

Прямой поток (TDL → SVG) и обратный (SVG → модель):

```
TDL текст → Лексер → Парсер → AST → Сборка модели → Валидация → Graphviz → SVG(data-*)
                                                                                  │
                              Pydantic-модель ← Валидация ← Парсер SVG ←──────────┘
```

Ключевые шаги прямого потока: `tdl_lexer` → `tdl_parser` → `tdl_ast` → `tdl_build`
→ `diagram.validate_all()` → `graphviz_render` (DOT → `dot` → SVG + обогащение
`data-*`). Обратный поток: `svg_parser` разбирает XML, извлекает `data-*`, собирает
`ClassDiagram` и снова валидирует, возвращая `ParseResult` с ошибками/предупреждениями
вместо исключений.

### Компоненты

#### Ядро модели (Pydantic)

- `models.py` — элементы UML: `Class`, `Attribute`, `Operation`, `Parameter`,
  `MultiplicityRange`; SVG-рендеринг отдельных элементов, полная валидация типов.
- `relationships.py` — отношения: `Association`/`AssociationEnd`, `Dependency`,
  `Generalization`, `Realization`; агрегация/композиция, стереотипы, n-арные ассоциации.
- `enums.py` — перечисления (видимость, стереотипы, типы агрегации).
- `diagram.py` — контейнер `ClassDiagram`, позиционирование, `validate_all()`,
  `to_svg()` (Graphviz) и legacy-рендеринг для совместимости.

#### Парсер TDL

- `tdl_lexer.py` — лексер (`lex`): ключевые слова, идентификаторы, литералы.
- `tdl_parser.py` — синтаксический анализатор (`parse_tdl`) → AST.
- `tdl_ast.py` — узлы AST: `Document`, `ClassDef`, `AttrDef`/`OpDef`, `AssocDef`/`DepDef`/`GenDef`.
- `tdl_build.py` — сборка `ClassDiagram` из AST (`build_diagram`).
- `tdl_run.py` — точка входа CLI (`tdl_to_svg`, `main`).

#### Генерация и парсинг SVG

- `graphviz_render.py` — DOT-раскладка через Graphviz, обогащение `data-*`-атрибутами.
- `svg_parser.py` — обратный парсинг SVG → модель (`parse_svg_to_diagram`, `ParseResult`),
  двухуровневая валидация (синтаксис + семантика).

#### Прочее

- `app.py` — Streamlit-приложение (рендер TDL и валидатор SVG).
- `export.py` — экспорт в PNG/JPG.

### Граф зависимостей

```
tdl_run  → tdl_lexer, tdl_parser, tdl_build, graphviz_render
app      → svg_parser, diagram, export, tdl_run (+ tdl_lexer/parser/build)
graphviz_render → diagram
svg_parser → models, relationships, diagram
diagram    → models, relationships
tdl_build  → tdl_ast, models, relationships, diagram
```

## Примеры и тесты (`examples/`)

- `example.tdl` — основной пример диаграммы.
- `error_*.tdl` — некорректные диаграммы для проверки валидации:
  `error_cycle` (цикл наследования), `error_multiple_inheritance` (конфликт типов),
  `error_unknown_class_assoc` / `error_unknown_general` (ссылка на несуществующий
  класс/родитель), `error_unknown_type_attr` (неизвестный тип атрибута).
- `09_02/imported_svg/` — сгенерированные SVG для проверки парсера.
- `imported_examples.py` — генерация тестовых SVG; `test_parser.py` — проверка
  парсинга и roundtrip (Pydantic → SVG → Pydantic → SVG, файлы идентичны).

## История разработки

Система собиралась поэтапно: (1) `data-*`-атрибуты классов, (2) `data-*` отношений,
(3) обратный парсер `svg_parser.py`, (4) проверка roundtrip `test_parser.py`,
(5) Streamlit-приложение. Итоговый цикл — детерминированный и обратимый:
`imported_examples` → Pydantic → SVG(`data-*`) → парсер → Pydantic → валидация → интерфейс.

## Итоги

Реализован полный цикл TDL-компилятора (лексер/парсер/AST/сборка модели) с переходом
от ручного позиционирования к автоматической раскладке Graphviz, обратный парсинг
SVG и семантическая валидация (5+ видов проверок), плюс веб-интерфейс с экспортом в
растр. Модель строго типизирована (Pydantic v2), архитектура модульная.
Ориентировочный объём — ~2500 строк кода.

## Структура каталога

```
ontol_v3/
├── uml_dsl/      пакет ядра: модель, TDL-парсер, рендер Graphviz, валидация, app
├── examples/     примеры TDL и тестовые SVG
└── README.md     данный документ
```
