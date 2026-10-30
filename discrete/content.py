"""
Загрузчик контента: каталог TDL-файлов --> одна ``ClassDiagram`` + граф запросов.

Источник истины --- текстовые слепки TDL в git; этот модуль их только читает 
(запись правок --- задача редактора).

Почему файлы склеиваются в один текст, а не разбираются по отдельности
(замерено на ядре): сборка модели требует, чтобы все упомянутые классификаторы
были объявлены в том же разборе. Отдельный файл со ссылкой наружу падает ---
``ValueError: Unknown classifier 'Понятие'``. А схема и экземпляры обязаны
попасть в ОДНУ диаграмму, иначе связь «instanceOf» не соединит запись базы с её
классом и запросы ``@meta=...`` перестанут работать. Поэтому загрузка
склеивает все ``.tdl`` и разбирает как единый текст.

Порядок файлов при этом не важен: ядро разрешает ссылки вперёд (тоже замерено).
Файлы всё равно сортируются по пути --- ради воспроизводимости склейки.

Цена склейки --- номера строк в ошибках съезжают, поэтому модуль ведёт карту
строк и переводит позицию обратно в «файл + строка», как требует §5.1.
"""
from __future__ import annotations

import bisect
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

from uml_dsl.diagram import ClassDiagram
from uml_dsl.tdl_build import build_diagram
from uml_dsl.tdl_lexer import LexerError, lex
from uml_dsl.tdl_parser import ParseError, parse_tdl

from ontol.query import (
    LabeledGraph,
    diagram_to_graph,
    find_cycles,
    nodes,
    query,
    rpq,
    rpq_reachable,
)

from .names import IDENTIFIER, VOCABULARY, Vocabulary
from .schema import Profile

#: Расширение файлов контента.
TDL_SUFFIX = ".tdl"

#: Позиция в тексте, которую ядро дописывает в сообщение об ошибке.
#: ``ParseError`` не сохраняет токен в атрибутах (только в тексте сообщения),
#: поэтому позицию приходится извлекать разбором строки. Правка ядра запрещена.
_POSITION_RE = re.compile(r"\(строка (\d+), столбец (\d+)\)")

#: Имя неизвестного классификатора в сообщении сборщика модели.
_UNKNOWN_RE = re.compile(r"Unknown classifier '([^']+)'")


@dataclass(frozen=True)
class SourceLocation:
    """Место в исходном контенте: файл, строка, столбец."""

    file: Path
    line: Optional[int] = None
    column: Optional[int] = None
    #: ``True``, если позиция восстановлена приблизительно (поиском по тексту).
    approximate: bool = False

    def __str__(self) -> str:
        place = str(self.file)
        if self.line is not None:
            place += f":{self.line}"
            if self.column is not None:
                place += f":{self.column}"
        return place + (" (приблизительно)" if self.approximate else "")


class ContentError(Exception):
    """
    Ошибка загрузки контента с указанием места в исходном файле.

    :param message: описание ошибки
    :param location: место в контенте, если удалось определить
    """

    def __init__(self, message: str, location: Optional[SourceLocation] = None) -> None:
        self.location = location
        self.raw_message = message
        super().__init__(f"{location}: {message}" if location else message)


@dataclass(frozen=True)
class Violation:
    """
    Нарушение смыслового инварианта онтологии (§4.5 ``docs/discrete-ontology.md``).

    В отличие от :class:`ContentError` это не поломка разбора, а содержательная
    ошибка в данных: контент разобрался, но онтология получилась неправильной.
    """

    invariant: str
    message: str
    nodes: Tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f" [{', '.join(self.nodes)}]" if self.nodes else ""
        return f"{self.invariant}: {self.message}{where}"


class _LineIndex:
    """
    Карта строк склеенного текста: глобальная строка --> (файл, его строка).

    Нужна, чтобы ошибка разбора указывала на файл преподавателя, а не на
    позицию в склейке, которой он никогда не видел.
    """

    def __init__(self) -> None:
        self._starts: List[int] = []   # глобальный номер первой строки файла
        self._files: List[Path] = []

    def add(self, file: Path, first_line: int) -> None:
        """
        Запомнить, что файл начинается с указанной глобальной строки.

        :param file: путь файла
        :param first_line: номер его первой строки в склеенном тексте (с 1)
        """
        self._starts.append(first_line)
        self._files.append(file)

    def resolve(self, global_line: int, column: Optional[int] = None,
                approximate: bool = False) -> Optional[SourceLocation]:
        """
        Перевести глобальный номер строки в место в конкретном файле.

        :param global_line: номер строки в склеенном тексте (с 1)
        :param column: номер столбца, если известен
        :param approximate: пометить позицию как приблизительную

        :return: место в исходном файле либо ``None``, если карта пуста
        """
        if not self._starts:
            return None
        index = max(bisect.bisect_right(self._starts, global_line) - 1, 0)
        return SourceLocation(
            file=self._files[index],
            line=global_line - self._starts[index] + 1,
            column=column,
            approximate=approximate,
        )

    def find_name(self, name: str) -> Optional[SourceLocation]:
        """
        Найти первое вхождение имени в файлах --- приблизительная локация.

        Нужна для ошибок сборщика модели: он сообщает «Unknown classifier 'X'»
        вовсе без позиции, и единственный способ помочь --- показать, где это
        имя упомянуто.

        :param name: искомое имя классификатора

        :return: приблизительное место либо ``None``
        """
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        for file in self._files:
            try:
                lines = file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    return SourceLocation(file=file, line=number, approximate=True)
        return None


@dataclass
class Content:
    """
    Загруженный контент: диаграмма, граф для запросов и сведения об источнике.

    :param diagram: схема и экземпляры в одной диаграмме классов
    :param graph: тот же контент как помеченный граф (``role_labels=True``)
    :param profile: профиль схемы, в котором контент разбирался
    :param vocabulary: словарь имён
    :param files: загруженные файлы в порядке склейки
    :param version: версия контента (git sha) либо ``None``
    :param violations: найденные нарушения инвариантов (пусто, если всё чисто)
    """

    diagram: ClassDiagram
    graph: LabeledGraph
    profile: Profile
    vocabulary: Vocabulary
    files: Tuple[Path, ...]
    version: Optional[str] = None
    violations: Tuple[Violation, ...] = ()

    @property
    def instances(self) -> Set[str]:
        """
        Записи базы --- узлы с исходящим ребром «instanceOf».

        Отделять их от классов схемы нужно потому, что схема и экземпляры
        лежат в одном графе: например, рефлексивная ассоциация
        ``ЕдиницаКонтента --требует--> ЕдиницаКонтента`` на уровне схемы сама
        выглядит петлёй, и содержательные инварианты обязаны её игнорировать.

        :return: множество имён узлов-экземпляров
        """
        return {src for src, _ in rpq(self.graph, "instanceOf")}

    def instances_of(self, class_name: str) -> Set[str]:
        """
        Записи базы, принадлежащие указанному классу онтологии.

        :param class_name: имя класса онтологии

        :return: множество имён узлов-экземпляров
        """
        return nodes(self.graph, f"@meta={class_name}")


def discover_files(root: Path) -> Tuple[Path, ...]:
    """
    Найти файлы контента в каталоге (рекурсивно), отсортированные по пути.

    :param root: корневой каталог контента

    :return: кортеж путей к ``.tdl``-файлам

    :raises ContentError: каталог не существует или в нём нет файлов контента
    """
    if not root.is_dir():
        raise ContentError(f"Каталог контента не найден: {root}")
    found = tuple(sorted(p for p in root.rglob(f"*{TDL_SUFFIX}") if p.is_file()))
    if not found:
        raise ContentError(f"В каталоге {root} нет файлов {TDL_SUFFIX}")
    return found


def _concatenate(files: Sequence[Path]) -> Tuple[str, _LineIndex]:
    """
    Склеить файлы в один текст, попутно построив карту строк.

    :param files: файлы контента в порядке склейки

    :return: пара (склеенный текст, карта строк)

    :raises ContentError: файл не читается
    """
    chunks: List[str] = []
    index = _LineIndex()
    line_no = 1
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContentError(f"Не удалось прочитать файл: {exc}",
                               SourceLocation(file=file)) from exc
        index.add(file, line_no)
        if not text.endswith("\n"):
            text += "\n"
        chunks.append(text)
        line_no += text.count("\n")
    return "".join(chunks), index


def _translate(exc: Exception, index: _LineIndex) -> ContentError:
    """
    Перевести ошибку ядра в :class:`ContentError` с местом в исходном файле.

    :param exc: исключение лексера, парсера или сборщика модели
    :param index: карта строк склейки

    :return: ошибка с локацией (насколько её удалось восстановить)
    """
    message = str(exc)

    # Лексер хранит позицию в атрибутах --- самый точный случай.
    if isinstance(exc, LexerError):
        return ContentError(
            _POSITION_RE.sub("", message).strip(),
            index.resolve(exc.line, exc.column),
        )

    # Парсер позицию в атрибутах не хранит, только в тексте сообщения.
    position = _POSITION_RE.search(message)
    if position:
        return ContentError(
            _POSITION_RE.sub("", message).strip(),
            index.resolve(int(position.group(1)), int(position.group(2))),
        )

    # Сборщик модели сообщает имя без позиции --- ищем имя по файлам.
    unknown = _UNKNOWN_RE.search(message)
    if unknown:
        name = unknown.group(1)
        return ContentError(
            f"Неизвестный классификатор {name!r}: он нигде не объявлен "
            f"(объявите «КЛАСС {name}» или исправьте опечатку)",
            index.find_name(name),
        )

    return ContentError(message)


def content_version(root: Path) -> Optional[str]:
    """
    Версия контента: короткий git sha, с пометкой ``+dirty`` при правках.

    Версия попадает в журнал вместе с каждой попыткой, чтобы задним числом было
    понятно, на какой версии базы студент отвечал (§5.1 ``docs/storage.md``).

    :param root: каталог контента

    :return: строка версии либо ``None``, если git недоступен
    """
    def git(*args: str) -> Optional[str]:
        """Выполнить git в каталоге контента, вернуть вывод или ``None``."""
        try:
            done = subprocess.run(
                ("git", *args), cwd=root, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    sha = git("rev-parse", "--short", "HEAD")
    if sha is None:
        return None
    # Путь передаётся как "." --- он разрешается относительно cwd, которым уже
    # является каталог контента; передать сюда str(root) значит искать
    # content/content и всегда получать «чисто».
    dirty = git("status", "--porcelain", "--", ".")
    return f"{sha}+dirty" if dirty else sha


# СМЫСЛОВЫЕ ИНВАРИАНТЫ

def check_invariants(graph: LabeledGraph, profile: Profile = Profile.FULL,
                     vocabulary: Vocabulary = VOCABULARY) -> List[Violation]:
    """
    Проверить смысловые инварианты онтологии.

    Состав проверок зависит от профиля: в ``CONCEPTS`` нет определений и
    доказательств как отдельных узлов, в ``TASKS`` нет и карты знаний.

    Каждая проверка формулируется ЗАПРОСОМ --- ищутся контрпримеры, после чего
    проверяется, что их множество пусто. Исключение помечено в коде: RPQ не
    выражает кардинальность, поэтому «не больше одного доказательства»
    подсчитывается на Python (§6.3 ТЗ).

    :param graph: граф контента (``role_labels=True``)
    :param profile: профиль схемы
    :param vocabulary: словарь имён

    :return: список нарушений; пустой список означает, что онтология корректна
    """
    v = vocabulary
    found: List[Violation] = []
    instances = {src for src, _ in rpq(graph, "instanceOf")}

    # 1. Циклов наследования быть не может ни в схеме, ни в записях.
    gen_cycles = find_cycles(graph, "gen")
    if gen_cycles:
        found.append(Violation(
            "нет циклов наследования",
            "классы образуют цикл по обобщению",
            tuple(gen_cycles),
        ))

    # 1a. Код записи должен быть адресуем узловым атомом запроса.
    #     Лексер паттернов не принимает точки, дефисы и пробелы, поэтому код
    #     вида «гр.10» молча ломает все запросы @код=..., а не выдаёт ошибку.
    bad_codes = sorted(
        f"{node}={code}"
        for node in instances
        if (code := graph.slot(node, v.slot_code)) is not None
        and not IDENTIFIER.match(str(code))
    )
    if bad_codes:
        found.append(Violation(
            "код адресуем запросом",
            f"код содержит символы, недопустимые в паттерне запроса "
            f"(точка, дефис, пробел) --- запросы «@{v.slot_code}=...» по нему "
            f"работать не будут",
            tuple(bad_codes),
        ))

    if profile is Profile.TASKS:
        return found  # карты знаний нет, проверять больше нечего

    # 2. Предпосылки не могут ходить по кругу. Проверяется только на записях:
    #    в схеме связь «требует» рефлексивна и сама по себе выглядит петлёй.
    requires_cycles = sorted(node for node in find_cycles(graph, v.role_requires)
                             if node in instances)
    if requires_cycles:
        found.append(Violation(
            "нет циклов в предпосылках",
            f"записи ссылаются друг на друга по «{v.role_requires}» по кругу",
            tuple(requires_cycles),
        ))

    if profile is Profile.CONCEPTS:
        return found  # определений и доказательств как узлов здесь нет

    # 3. Каждое определение обязано определять понятие.
    undefined = sorted(
        node for node in nodes(graph, f"@meta={v.definition}")
        if not rpq_reachable(graph, node, v.role_defines)
    )
    if undefined:
        found.append(Violation(
            "определение определяет понятие",
            f"нет исходящей связи «{v.role_defines}»",
            tuple(undefined),
        ))

    # 4. У утверждения не больше одного доказательства.
    #    Кардинальность запросом не выражается (§6.3 ТЗ): запрос даёт множество
    #    доказательств, а сравнение его размера с единицей делается здесь.
    statements = nodes(graph, f"@meta={v.theorem}") | nodes(graph, f"@meta={v.lemma}")
    overproved = sorted(
        statement for statement in statements
        if len(query(graph, v.role_proves, dst=statement)) > 1
    )
    if overproved:
        found.append(Violation(
            "не больше одного доказательства",
            f"несколько записей ссылаются по «{v.role_proves}» на одно утверждение",
            tuple(overproved),
        ))

    # 5. Шаг доказательства обоснован только тем, что доступно его тезису.
    for proof in sorted(nodes(graph, f"@meta={v.proof}")):
        justified_by = rpq_reachable(graph, proof, f"comp {v.role_justified_by}")
        for thesis in sorted(rpq_reachable(graph, proof, v.role_proves)):
            available = rpq_reachable(graph, thesis, f"{v.role_requires}*")
            extra = justified_by - available
            if extra:
                found.append(Violation(
                    "шаг обоснован доступным",
                    f"доказательство {proof!r} опирается на то, чего "
                    f"{thesis!r} не требует",
                    tuple(sorted(extra)),
                ))
    return found


# ЗАГРУЗКА

def load_content(root: Path, *, profile: Profile = Profile.FULL,
                 vocabulary: Vocabulary = VOCABULARY,
                 validate: bool = True, strict: bool = True) -> Content:
    """
    Загрузить контент из каталога TDL-файлов.

    Загрузка идемпотентна и не зависит от порядка файлов на диске: файлы
    сортируются по пути, а ядро разрешает ссылки вперёд.

    Валидация идёт в два этапа, как требует: 
    сначала структурная (``ClassDiagram.validate_all`` ядра), затем смысловая
    (инварианты онтологии запросами, см. :func:`check_invariants`).

    :param root: каталог контента
    :param profile: профиль схемы, под который проверяются инварианты
    :param vocabulary: словарь имён
    :param validate: выполнять ли валидацию (``False`` --- только разбор)
    :param strict: считать нарушения инвариантов ошибкой; при ``False``
        они возвращаются в :attr:`Content.violations`, а загрузка проходит

    :return: загруженный контент

    :raises ContentError: контент не читается, не разбирается, не проходит
        структурную валидацию либо (при ``strict``) нарушает инварианты
    """
    files = discover_files(root)
    text, index = _concatenate(files)

    try:
        diagram = build_diagram(parse_tdl(lex(text)))
    except (LexerError, ParseError, ValueError) as exc:
        raise _translate(exc, index) from exc

    if validate:
        # Этап 1: структурная валидация ядра.
        try:
            diagram.validate_all()
        except Exception as exc:  # ядро бросает разные типы исключений
            raise _translate(exc, index) from exc

    graph = diagram_to_graph(diagram, role_labels=True)

    violations: Tuple[Violation, ...] = ()
    if validate:
        # Этап 2: смысловые инварианты --- запросами к онтологии.
        found = check_invariants(graph, profile, vocabulary)
        if found and strict:
            listing = "\n  - ".join(str(item) for item in found)
            raise ContentError(
                f"Контент нарушает инварианты онтологии:\n  - {listing}"
            )
        violations = tuple(found)

    return Content(
        diagram=diagram,
        graph=graph,
        profile=profile,
        vocabulary=vocabulary,
        files=files,
        version=content_version(root),
        violations=violations,
    )
