"""
Загрузчик контента: склейка TDL-файлов, диагностика ошибок, инварианты.

Контент для тестов собирается во временном каталоге прямо здесь --- так тесты
не зависят от реального наполнения в ``content/`` и не ломаются, когда
преподаватель правит курс.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from discrete import CYRILLIC, Profile, build_schema
from discrete.content import (
    Content,
    ContentError,
    Violation,
    check_invariants,
    content_version,
    discover_files,
    load_content,
)
from ontol.query import diagram_to_graph, rpq_reachable

V = CYRILLIC

#: Схема в TDL. Собирается из словаря, чтобы тест не расходился со схемой кода.
SCHEMA_TDL = f"""
КЛАСС {V.unit} АБСТРАКТНЫЙ
  АТРИБУТЫ
    + {V.slot_code} : Строка
КОНЕЦ КЛАСС

КЛАСС {V.concept}
КОНЕЦ КЛАСС

КЛАСС {V.definition}
КОНЕЦ КЛАСС

КЛАСС {V.statement} АБСТРАКТНЫЙ
КОНЕЦ КЛАСС

КЛАСС {V.theorem}
КОНЕЦ КЛАСС

КЛАСС {V.proof}
КОНЕЦ КЛАСС

КЛАСС {V.proof_step}
КОНЕЦ КЛАСС

ОБОБЩЕНИЕ {V.concept} -> {V.unit}
ОБОБЩЕНИЕ {V.definition} -> {V.unit}
ОБОБЩЕНИЕ {V.statement} -> {V.unit}
ОБОБЩЕНИЕ {V.proof} -> {V.unit}
ОБОБЩЕНИЕ {V.theorem} -> {V.statement}

КОМПОЗИЦИЯ
  {V.proof} 1
  --
  {V.proof_step} *

АССОЦИАЦИЯ
  {V.definition} 1
  --
  {V.concept} 1 : {V.role_defines}

АССОЦИАЦИЯ
  {V.unit} *
  --
  {V.unit} * : {V.role_requires}

АССОЦИАЦИЯ
  {V.proof} 1
  --
  {V.statement} 1 : {V.role_proves}

АССОЦИАЦИЯ
  {V.proof_step} *
  --
  {V.unit} * : {V.role_justified_by}
"""

#: Корректные записи: понятие, его определение, теорема с доказательством.
CONTENT_TDL = f"""
КЛАСС граф
КОНЕЦ КЛАСС

КЛАСС опрГрафа
КОНЕЦ КЛАСС

КЛАСС теорема1
КОНЕЦ КЛАСС

КЛАСС док1
КОНЕЦ КЛАСС

КЛАСС шаг1
КОНЕЦ КЛАСС

ЗАВИСИМОСТЬ граф -> {V.concept} экземпляр
ЗАВИСИМОСТЬ опрГрафа -> {V.definition} экземпляр
ЗАВИСИМОСТЬ теорема1 -> {V.theorem} экземпляр
ЗАВИСИМОСТЬ док1 -> {V.proof} экземпляр
ЗАВИСИМОСТЬ шаг1 -> {V.proof_step} экземпляр

АССОЦИАЦИЯ
  опрГрафа 1
  --
  граф 1 : {V.role_defines}

АССОЦИАЦИЯ
  теорема1 1
  --
  граф 1 : {V.role_requires}

АССОЦИАЦИЯ
  док1 1
  --
  теорема1 1 : {V.role_proves}

КОМПОЗИЦИЯ
  док1 1
  --
  шаг1 1

АССОЦИАЦИЯ
  шаг1 1
  --
  граф 1 : {V.role_justified_by}
"""


def _write(root: Path, **files: str) -> Path:
    """
    Создать каталог контента с указанными файлами.

    :param root: каталог, в котором создаются файлы
    :param files: отображение «имя без расширения -> текст TDL»

    :return: тот же каталог
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / f"{name}.tdl").write_text(text, encoding="utf-8")
    return root


@pytest.fixture()
def content_dir(tmp_path: Path) -> Path:
    """Каталог с корректным контентом: схема + записи."""
    return _write(tmp_path / "content", schema=SCHEMA_TDL, topic=CONTENT_TDL)


# ──────────────────────────── поиск файлов ────────────────────────────

def test_discover_files_sorted_and_recursive(tmp_path: Path) -> None:
    """
    Поиск рекурсивный, порядок --- по полному пути (не по имени файла), так что
    файл в подкаталоге идёт после файла рядом с корнем. Важен сам детерминизм:
    от порядка склейки результат не зависит, но склейка должна быть одинаковой
    при каждом запуске.
    """
    root = _write(tmp_path / "c", b_second=SCHEMA_TDL)
    _write(root / "topics", a_first=CONTENT_TDL)
    found = discover_files(root)
    assert [p.relative_to(root).as_posix() for p in found] == [
        "b_second.tdl", "topics/a_first.tdl",
    ]
    assert found == discover_files(root)   # порядок воспроизводим


def test_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="не найден"):
        discover_files(tmp_path / "нет-такого")


def test_empty_directory_is_reported(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ContentError, match="нет файлов"):
        discover_files(tmp_path / "empty")


# ──────────────────────────── загрузка ────────────────────────────

def test_loads_schema_and_records_into_one_diagram(content_dir: Path) -> None:
    """
    Схема и записи обязаны попасть в ОДНУ диаграмму, иначе «instanceOf» не
    соединит запись с её классом и запросы ``@meta=`` не сработают.
    """
    content = load_content(content_dir)
    assert isinstance(content, Content)
    assert V.concept in content.graph.nodes      # класс схемы
    assert "граф" in content.graph.nodes          # запись
    assert ("граф", "instanceOf", V.concept) in content.graph.edges


def test_records_are_separated_from_schema(content_dir: Path) -> None:
    content = load_content(content_dir)
    assert content.instances == {"граф", "опрГрафа", "теорема1", "док1", "шаг1"}
    # классы схемы записями не считаются
    assert V.concept not in content.instances
    assert content.instances_of(V.concept) == {"граф"}
    assert content.instances_of(V.theorem) == {"теорема1"}


def test_queries_work_on_loaded_content(content_dir: Path) -> None:
    content = load_content(content_dir)
    assert rpq_reachable(content.graph, "теорема1", V.role_requires) == {"граф"}
    assert rpq_reachable(content.graph, "док1", V.role_proves) == {"теорема1"}


def test_load_is_order_independent(tmp_path: Path) -> None:
    """
    Имя файла влияет на порядок склейки, но не на результат: ядро разрешает
    ссылки вперёд.
    """
    forward = _write(tmp_path / "a", _1_schema=SCHEMA_TDL, _2_topic=CONTENT_TDL)
    reversed_order = _write(tmp_path / "b", _1_topic=CONTENT_TDL, _2_schema=SCHEMA_TDL)
    first = load_content(forward)
    second = load_content(reversed_order)
    assert first.graph.nodes == second.graph.nodes
    assert set(first.graph.edges) == set(second.graph.edges)


def test_load_is_idempotent(content_dir: Path) -> None:
    first = load_content(content_dir)
    second = load_content(content_dir)
    assert first.graph.nodes == second.graph.nodes
    assert set(first.graph.edges) == set(second.graph.edges)


def test_file_without_trailing_newline_is_handled(tmp_path: Path) -> None:
    """Склейка не должна слипать последнюю строку файла с первой строкой следующего."""
    root = tmp_path / "c"
    root.mkdir()
    (root / "1.tdl").write_text(SCHEMA_TDL.rstrip("\n"), encoding="utf-8")
    (root / "2.tdl").write_text(CONTENT_TDL.rstrip("\n"), encoding="utf-8")
    content = load_content(root)
    assert "граф" in content.graph.nodes


# ──────────────────────── диагностика ошибок ────────────────────────

def test_lexer_error_points_at_the_right_file_and_line(tmp_path: Path) -> None:
    """
    Файлы склеиваются, поэтому номер строки от ядра относится к склейке.
    Загрузчик обязан перевести его обратно в файл преподавателя.
    """
    broken = "КЛАСС Хорошо\nКОНЕЦ КЛАСС\nКЛАСС Пло%хо\nКОНЕЦ КЛАСС\n"
    root = _write(tmp_path / "c", _1_schema=SCHEMA_TDL, _2_broken=broken)
    with pytest.raises(ContentError) as exc:
        load_content(root)
    assert exc.value.location is not None
    assert exc.value.location.file.name == "_2_broken.tdl"
    assert exc.value.location.line == 3      # не глобальная строка склейки
    assert exc.value.location.approximate is False


def test_parse_error_points_at_the_right_file_and_line(tmp_path: Path) -> None:
    # двоеточие в имени класса: парсер ждёт КОНЕЦ
    broken = "КЛАСС Хорошо\nКОНЕЦ КЛАСС\nКЛАСС граф : Понятие\nКОНЕЦ КЛАСС\n"
    root = _write(tmp_path / "c", _1_schema=SCHEMA_TDL, _2_broken=broken)
    with pytest.raises(ContentError) as exc:
        load_content(root)
    assert exc.value.location is not None
    assert exc.value.location.file.name == "_2_broken.tdl"
    assert exc.value.location.line == 3


def test_unknown_classifier_is_explained(tmp_path: Path) -> None:
    """
    Сборщик модели сообщает имя без позиции, поэтому локация приблизительная ---
    первое вхождение имени в файлах.
    """
    broken = "ОБОБЩЕНИЕ НетТакогоКласса -> Понятие\n"
    root = _write(tmp_path / "c", _1_schema=SCHEMA_TDL, _2_broken=broken)
    with pytest.raises(ContentError) as exc:
        load_content(root)
    assert "НетТакогоКласса" in str(exc.value)
    assert "нигде не объявлен" in str(exc.value)
    assert exc.value.location is not None
    assert exc.value.location.approximate is True


def test_unreadable_directory_entry(tmp_path: Path) -> None:
    root = _write(tmp_path / "c", schema=SCHEMA_TDL)
    content = load_content(root, validate=False)
    assert content.files == (root / "schema.tdl",)


# ──────────────────────── смысловые инварианты ────────────────────────

def test_valid_content_has_no_violations(content_dir: Path) -> None:
    content = load_content(content_dir)
    assert content.violations == ()


def test_schema_reflexive_requires_is_not_a_cycle(content_dir: Path) -> None:
    """
    В схеме связь «требует» рефлексивна (ЕдиницаКонтента -> ЕдиницаКонтента),
    и сама по себе она выглядит петлёй. Инвариант обязан смотреть только на
    записи, иначе любая корректная онтология считалась бы битой.
    """
    content = load_content(content_dir)
    from ontol.query import find_cycles
    # петля в схеме действительно есть
    assert V.unit in find_cycles(content.graph, V.role_requires)
    # но violationм она не признана
    assert content.violations == ()


def test_cycle_in_requires_is_reported(tmp_path: Path) -> None:
    cyclic_tdl = f"""
КЛАСС а
КОНЕЦ КЛАСС
КЛАСС б
КОНЕЦ КЛАСС
ЗАВИСИМОСТЬ а -> {V.concept} экземпляр
ЗАВИСИМОСТЬ б -> {V.concept} экземпляр
АССОЦИАЦИЯ
  а 1
  --
  б 1 : {V.role_requires}
АССОЦИАЦИЯ
  б 1
  --
  а 1 : {V.role_requires}
"""
    root = _write(tmp_path / "c", schema=SCHEMA_TDL, bad=cyclic_tdl)
    with pytest.raises(ContentError, match="циклов в предпосылках"):
        load_content(root)
    # нестрогий режим: загрузка проходит, violation возвращается
    content = load_content(root, strict=False)
    assert len(content.violations) == 1
    assert content.violations[0].nodes == ("а", "б")


def test_definition_without_concept_is_reported(tmp_path: Path) -> None:
    orphan_definition = f"""
КЛАСС опрБезПонятия
КОНЕЦ КЛАСС
ЗАВИСИМОСТЬ опрБезПонятия -> {V.definition} экземпляр
"""
    root = _write(tmp_path / "c", schema=SCHEMA_TDL, bad=orphan_definition)
    content = load_content(root, strict=False)
    assert any(v.invariant == "определение определяет понятие"
               for v in content.violations)
    assert any("опрБезПонятия" in v.nodes for v in content.violations)


def test_two_proofs_for_one_statement_are_reported(tmp_path: Path) -> None:
    """Кардинальность запросом не выражается — проверка считает на Python."""
    two_proofs = f"""
КЛАСС т
КОНЕЦ КЛАСС
КЛАСС д1
КОНЕЦ КЛАСС
КЛАСС д2
КОНЕЦ КЛАСС
ЗАВИСИМОСТЬ т -> {V.theorem} экземпляр
ЗАВИСИМОСТЬ д1 -> {V.proof} экземпляр
ЗАВИСИМОСТЬ д2 -> {V.proof} экземпляр
АССОЦИАЦИЯ
  д1 1
  --
  т 1 : {V.role_proves}
АССОЦИАЦИЯ
  д2 1
  --
  т 1 : {V.role_proves}
"""
    root = _write(tmp_path / "c", schema=SCHEMA_TDL, bad=two_proofs)
    content = load_content(root, strict=False)
    assert any(v.invariant == "не больше одного доказательства"
               for v in content.violations)


def test_step_justified_by_unavailable_unit_is_reported(tmp_path: Path) -> None:
    """
    Инвариант 5: шаг доказательства опирается на то, чего тезис не требует.
    Проверка — разность двух запросов (§6.4 ТЗ).
    """
    bad_justification = f"""
КЛАСС постороннее
КОНЕЦ КЛАСС
КЛАСС т
КОНЕЦ КЛАСС
КЛАСС д
КОНЕЦ КЛАСС
КЛАСС ш
КОНЕЦ КЛАСС
ЗАВИСИМОСТЬ постороннее -> {V.concept} экземпляр
ЗАВИСИМОСТЬ т -> {V.theorem} экземпляр
ЗАВИСИМОСТЬ д -> {V.proof} экземпляр
ЗАВИСИМОСТЬ ш -> {V.proof_step} экземпляр
АССОЦИАЦИЯ
  д 1
  --
  т 1 : {V.role_proves}
КОМПОЗИЦИЯ
  д 1
  --
  ш 1
АССОЦИАЦИЯ
  ш 1
  --
  постороннее 1 : {V.role_justified_by}
"""
    root = _write(tmp_path / "c", schema=SCHEMA_TDL, bad=bad_justification)
    content = load_content(root, strict=False)
    violation = next(v for v in content.violations
                     if v.invariant == "шаг обоснован доступным")
    assert violation.nodes == ("постороннее",)


def test_invariants_depend_on_profile(content_dir: Path) -> None:
    """
    В профиле TASKS карты знаний нет, в CONCEPTS нет определений как узлов ---
    проверки, которым не на чем работать, не должны выполняться.
    """
    graph = load_content(content_dir, validate=False).graph
    assert check_invariants(graph, Profile.TASKS) == []
    # в CONCEPTS проверка определений не выполняется, цикл в gen всё равно виден
    assert all(v.invariant != "определение определяет понятие"
               for v in check_invariants(graph, Profile.CONCEPTS))


def test_validate_false_skips_checks(tmp_path: Path) -> None:
    cyclic_tdl = f"""
КЛАСС а
КОНЕЦ КЛАСС
КЛАСС б
КОНЕЦ КЛАСС
ЗАВИСИМОСТЬ а -> {V.concept} экземпляр
ЗАВИСИМОСТЬ б -> {V.concept} экземпляр
АССОЦИАЦИЯ
  а 1
  --
  б 1 : {V.role_requires}
АССОЦИАЦИЯ
  б 1
  --
  а 1 : {V.role_requires}
"""
    root = _write(tmp_path / "c", schema=SCHEMA_TDL, bad=cyclic_tdl)
    content = load_content(root, validate=False)   # не бросает
    assert content.violations == ()


# ──────────────────────────── версия контента ────────────────────────────

def test_version_is_none_outside_git(tmp_path: Path) -> None:
    root = _write(tmp_path / "c", schema=SCHEMA_TDL)
    # tmp_path вне git-репозитория: версии нет, но загрузка работает
    assert content_version(root) is None
    assert load_content(root, validate=False).version is None


# ──────────────────── согласие с схемой из кода ────────────────────

def test_real_schema_file_matches_code(tmp_path: Path) -> None:
    """
    ``content/schema.tdl`` обязан совпадать со схемой, которую строит
    :func:`discrete.schema.build_schema` --- иначе наполнение разойдётся с
    кодом, и запросы начнут врать.
    """
    schema_file = Path(__file__).resolve().parent.parent / "content" / "schema.tdl"
    if not schema_file.is_file():
        pytest.skip("content/schema.tdl ещё не создан")

    root = _write(tmp_path / "c", schema=schema_file.read_text(encoding="utf-8"))
    from_file = load_content(root, validate=False).graph
    from_code = diagram_to_graph(build_schema(Profile.FULL), role_labels=True)

    assert from_file.nodes == from_code.nodes
    assert set(from_file.edges) == set(from_code.edges)
    assert from_file.labels() == from_code.labels()
