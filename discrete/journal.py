"""
Журнал: что система выдала студентам и что они ответили.

Журнал --- ВТОРОЕ хранилище, отдельное от контента, и это не деталь реализации, 
а следствие природы данных: контент --- редактируемый справочник (нужны история 
и ревью, правок мало), журнал --- событийный поток (правок нет вообще, зато 
конкурентные вставки и транзакции).

Три принципа, заложенные в схему:

1. **Только дописывание.** Правок прошлых записей не предусмотрено, и это
   закреплено триггерами SQLite, а не договорённостью: ``UPDATE``/``DELETE`` по
   журнальным таблицам отклоняются на уровне базы.
2. **Ответ хранится в исходном виде**, а не только «верно/неверно». Иначе после
   исправления ошибки в контенте старые ответы невозможно перепроверить.
3. **Ссылки на контент --- только строковым кодом** (слот ``код`` единицы). 
   Никаких внешних ключей в контент: он версионируется в git и живёт своей 
   жизнью, а запись журнала должна оставаться читаемой даже после удаления 
   единицы из базы.

Переход на PostgreSQL (когда появится несколько экземпляров приложения)
означает другую реализацию этого же API: SQL не протекает за границы модуля,
а прикладной код знает только методы :class:`Journal`.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: Версия схемы журнала; хранится в ``PRAGMA user_version``.
SCHEMA_VERSION = 1


class Verdict(str, Enum):
    """Результат проверки ответа."""

    #: Ответ верен.
    CORRECT = "correct"
    #: Ответ неверен.
    INCORRECT = "incorrect"
    #: Ответ верен частично (например, перечислено не всё).
    PARTIAL = "partial"
    #: Студент пропустил задание.
    SKIPPED = "skipped"


def _now() -> str:
    """
    Текущий момент в UTC как строка ISO-8601.

    SQLite не имеет типа даты; текстовое представление в UTC и сортируется
    правильно, и читается человеком при разборе инцидентов.

    :return: timestamp времени
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Attempt:
    """
    Одна попытка студента --- запись журнала.

    :param id: идентификатор попытки
    :param issue_id: выданный вариант, на который отвечали
    :param student: идентификатор студента
    :param task_code: код задачи в контенте (строкой, не ссылкой)
    :param answer: ответ студента в исходном виде
    :param verdict: результат проверки
    :param content_version: версия контента на момент проверки
    :param created_at: когда попытка записана (UTC, ISO-8601)
    :param details: разбор проверки (пропущенное, лишнее, класс ошибки)
    """

    id: int
    issue_id: int
    student: str
    task_code: str
    answer: str
    verdict: Verdict
    content_version: Optional[str]
    created_at: str
    details: Mapping[str, Any]


@dataclass(frozen=True)
class Issue:
    """
    Выданный студенту вариант задания.

    :param id: идентификатор выдачи
    :param session_id: учебная сессия
    :param student: идентификатор студента
    :param task_code: код задачи в контенте
    :param seed: сид генератора варианта --- по нему вариант воспроизводим
    :param content_version: версия контента на момент выдачи
    :param created_at: когда выдано (UTC, ISO-8601)
    """

    id: int
    session_id: int
    student: str
    task_code: str
    seed: int
    content_version: Optional[str]
    created_at: str


#: Схема журнала. Триггеры делают таблицы append-only на уровне базы.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student         TEXT    NOT NULL,
    content_version TEXT,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS issues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    -- код задачи в контенте: строка, а НЕ внешний ключ (см. docstring модуля)
    task_code       TEXT    NOT NULL,
    seed            INTEGER NOT NULL,
    content_version TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id        INTEGER NOT NULL REFERENCES issues(id),
    -- ответ в ИСХОДНОМ виде: нужен, чтобы перепроверить после правки контента
    answer          TEXT    NOT NULL,
    verdict         TEXT    NOT NULL,
    content_version TEXT,
    created_at      TEXT    NOT NULL,
    details         TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_issues_session  ON issues(session_id);
CREATE INDEX IF NOT EXISTS idx_issues_task     ON issues(task_code);
CREATE INDEX IF NOT EXISTS idx_attempts_issue  ON attempts(issue_id);

-- Журнал только дописывается. Запрет на уровне базы, а не договорённости:
-- переписанная задним числом попытка сделала бы журнал бесполезным как
-- свидетельство о том, что происходило на самом деле.
CREATE TRIGGER IF NOT EXISTS issues_no_update
BEFORE UPDATE ON issues
BEGIN
    SELECT RAISE(ABORT, 'журнал только дописывается: issues нельзя изменять');
END;

CREATE TRIGGER IF NOT EXISTS issues_no_delete
BEFORE DELETE ON issues
BEGIN
    SELECT RAISE(ABORT, 'журнал только дописывается: issues нельзя удалять');
END;

CREATE TRIGGER IF NOT EXISTS attempts_no_update
BEFORE UPDATE ON attempts
BEGIN
    SELECT RAISE(ABORT, 'журнал только дописывается: attempts нельзя изменять');
END;

CREATE TRIGGER IF NOT EXISTS attempts_no_delete
BEFORE DELETE ON attempts
BEGIN
    SELECT RAISE(ABORT, 'журнал только дописывается: attempts нельзя удалять');
END;

-- Сессию нужно закрывать, поэтому полный запрет здесь неуместен: разрешено
-- выставить finished_at один раз, всё остальное неизменяемо.
CREATE TRIGGER IF NOT EXISTS sessions_append_only
BEFORE UPDATE ON sessions
WHEN OLD.student         IS NOT NEW.student
  OR OLD.content_version IS NOT NEW.content_version
  OR OLD.started_at      IS NOT NEW.started_at
  OR OLD.finished_at     IS NOT NULL
BEGIN
    SELECT RAISE(ABORT,
        'журнал только дописывается: у сессии можно один раз выставить finished_at');
END;

CREATE TRIGGER IF NOT EXISTS sessions_no_delete
BEFORE DELETE ON sessions
BEGIN
    SELECT RAISE(ABORT, 'журнал только дописывается: sessions нельзя удалять');
END;
"""


class JournalError(Exception):
    """Ошибка работы с журналом."""


class Journal:
    """
    Журнал попыток на SQLite.

    Соединение открывается на всё время жизни объекта; записи идут в одной
    транзакции каждая. Вокруг операций стоит блокировка, потому что веб-слой
    (Streamlit) обслуживает запросы в разных потоках, а одно соединение
    sqlite3 не потокобезопасно.

    Использование::

        with Journal(Path("var/journal.sqlite3")) as journal:
            session = journal.start_session("ст-123", content.version)
            issue = journal.issue(session, "гр.10", seed=42)
            journal.record_attempt(issue, "граф, паросочетание", Verdict.CORRECT)
    """

    def __init__(self, path: Path, *, migrate: bool = True) -> None:
        """
        :param path: файл базы; родительские каталоги создаются
        :param migrate: применить миграции при открытии

        :raises JournalError: база не открывается или схема новее кода
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        try:
            # check_same_thread=False --- доступ сериализуется self._lock
            self._conn = sqlite3.connect(
                self.path, check_same_thread=False, isolation_level="DEFERRED",
            )
        except sqlite3.Error as exc:
            raise JournalError(f"Не удалось открыть журнал {self.path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL: читатели не блокируют писателя --- выдача заданий не ждёт записи
        self._conn.execute("PRAGMA journal_mode = WAL")
        if migrate:
            self.migrate()

    # ЖИЗНЕННЫЙ ЦИКЛ

    def migrate(self) -> int:
        """
        Применить миграции схемы. Идемпотентно.

        :return: версия схемы после миграции

        :raises JournalError: база создана более новой версией кода
        """
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise JournalError(
                    f"Журнал {self.path} создан более новой версией кода "
                    f"(схема {current}, поддерживается {SCHEMA_VERSION})"
                )
            if current == SCHEMA_VERSION:
                return current
            with self._conn:
                self._conn.executescript(_SCHEMA)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return SCHEMA_VERSION

    def close(self) -> None:
        """Закрыть соединение с базой."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ЗАПИСЬ

    def start_session(self, student: str,
                      content_version: Optional[str] = None) -> int:
        """
        Открыть учебную сессию.

        :param student: идентификатор студента
        :param content_version: версия контента (git sha из
            :func:`discrete.content.content_version`)

        :return: идентификатор сессии
        """
        return self._insert(
            "INSERT INTO sessions (student, content_version, started_at) "
            "VALUES (?, ?, ?)",
            (student, content_version, _now()),
        )

    def finish_session(self, session_id: int) -> None:
        """
        Закрыть сессию. Повторное закрытие отклоняется базой.

        :param session_id: идентификатор сессии

        :raises JournalError: сессия не найдена либо уже закрыта
        """
        with self._lock, self._conn:
            try:
                cursor = self._conn.execute(
                    "UPDATE sessions SET finished_at = ? WHERE id = ?",
                    (_now(), session_id),
                )
            except sqlite3.IntegrityError as exc:
                raise JournalError(f"Сессия {session_id} уже закрыта: {exc}") from exc
            if cursor.rowcount == 0:
                raise JournalError(f"Сессия {session_id} не найдена")

    def issue(self, session_id: int, task_code: str, seed: int,
              content_version: Optional[str] = None) -> int:
        """
        Записать выдачу варианта задания.

        Вариант не хранится целиком: он воспроизводим по паре «код задачи + сид»
        детерминированным генератором, поэтому в журнале лежит только сид.

        :param session_id: сессия, в рамках которой выдано задание
        :param task_code: код задачи в контенте
        :param seed: сид генератора варианта
        :param content_version: версия контента на момент выдачи

        :return: идентификатор выдачи

        :raises JournalError: сессия не найдена
        """
        try:
            return self._insert(
                "INSERT INTO issues (session_id, task_code, seed, content_version, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, task_code, seed, content_version, _now()),
            )
        except JournalError as exc:
            raise JournalError(
                f"Не удалось записать выдачу для сессии {session_id}: {exc}"
            ) from exc

    def record_attempt(self, issue_id: int, answer: str, verdict: Verdict,
                       content_version: Optional[str] = None,
                       details: Optional[Mapping[str, Any]] = None) -> int:
        """
        Записать попытку студента.

        :param issue_id: выданный вариант, на который отвечали
        :param answer: ответ в ИСХОДНОМ виде (не только «верно/неверно»)
        :param verdict: результат проверки
        :param content_version: версия контента на момент проверки
        :param details: разбор проверки (пропущенное, лишнее, класс ошибки) ---
            сохраняется как JSON, пригодится для подсказок и аналитики

        :return: идентификатор попытки

        :raises JournalError: выдача не найдена
        """
        try:
            payload = json.dumps(dict(details or {}), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise JournalError(f"Разбор проверки не сериализуется в JSON: {exc}") from exc
        return self._insert(
            "INSERT INTO attempts (issue_id, answer, verdict, content_version, "
            "created_at, details) VALUES (?, ?, ?, ?, ?, ?)",
            (issue_id, answer, Verdict(verdict).value, content_version,
             _now(), payload),
        )

    def _insert(self, sql: str, params: Sequence[Any]) -> int:
        """
        Выполнить вставку в одной транзакции и вернуть идентификатор строки.

        :param sql: SQL-запрос вставки
        :param params: параметры запроса

        :return: ``rowid`` вставленной строки

        :raises JournalError: нарушена целостность либо ошибка базы
        """
        with self._lock, self._conn:
            try:
                cursor = self._conn.execute(sql, tuple(params))
            except sqlite3.IntegrityError as exc:
                raise JournalError(f"Запись отклонена базой: {exc}") from exc
            except sqlite3.Error as exc:
                raise JournalError(f"Ошибка журнала: {exc}") from exc
            return int(cursor.lastrowid or 0)

    # ЧТЕНИЕ

    def attempts(self, *, student: Optional[str] = None,
                 task_code: Optional[str] = None) -> List[Attempt]:
        """
        Попытки, при необходимости отфильтрованные по студенту и задаче.

        :param student: идентификатор студента либо ``None`` (все)
        :param task_code: код задачи либо ``None`` (все)

        :return: список попыток в порядке записи
        """
        sql = [
            "SELECT a.id, a.issue_id, s.student, i.task_code, a.answer, a.verdict,",
            "       a.content_version, a.created_at, a.details",
            "FROM attempts a",
            "JOIN issues i   ON i.id = a.issue_id",
            "JOIN sessions s ON s.id = i.session_id",
        ]
        where: List[str] = []
        params: List[Any] = []
        if student is not None:
            where.append("s.student = ?")
            params.append(student)
        if task_code is not None:
            where.append("i.task_code = ?")
            params.append(task_code)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY a.id")

        with self._lock:
            rows = self._conn.execute("\n".join(sql), tuple(params)).fetchall()
        return [
            Attempt(
                id=row["id"],
                issue_id=row["issue_id"],
                student=row["student"],
                task_code=row["task_code"],
                answer=row["answer"],
                verdict=Verdict(row["verdict"]),
                content_version=row["content_version"],
                created_at=row["created_at"],
                details=json.loads(row["details"]),
            )
            for row in rows
        ]

    def issues(self, *, session_id: Optional[int] = None) -> List[Issue]:
        """
        Выданные варианты, при необходимости в рамках одной сессии.

        :param session_id: идентификатор сессии либо ``None`` (все)

        :return: список выдач в порядке записи
        """
        sql = (
            "SELECT i.id, i.session_id, s.student, i.task_code, i.seed, "
            "       i.content_version, i.created_at "
            "FROM issues i JOIN sessions s ON s.id = i.session_id"
        )
        params: Tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE i.session_id = ?"
            params = (session_id,)
        sql += " ORDER BY i.id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            Issue(
                id=row["id"],
                session_id=row["session_id"],
                student=row["student"],
                task_code=row["task_code"],
                seed=row["seed"],
                content_version=row["content_version"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def task_stats(self, student: str) -> Dict[str, Tuple[int, int]]:
        """
        Статистика студента по ЗАДАЧАМ: сколько верных из сколького.

        Статистика здесь --- по задачам, а не по единицам контента, и это
        намеренно: связь «задача проверяет единицу» лежит в онтологии, а не в
        журнале. Перевод в освоенность единиц делает прикладной код запросом к
        онтологии --- журнал про контент ничего не знает (§5.3).

        :param student: идентификатор студента

        :return: отображение «код задачи -> (верных, всего)»
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT i.task_code AS code, "
                "       SUM(CASE WHEN a.verdict = ? THEN 1 ELSE 0 END) AS correct, "
                "       COUNT(*) AS total "
                "FROM attempts a "
                "JOIN issues i   ON i.id = a.issue_id "
                "JOIN sessions s ON s.id = i.session_id "
                "WHERE s.student = ? "
                "GROUP BY i.task_code",
                (Verdict.CORRECT.value, student),
            ).fetchall()
        return {row["code"]: (row["correct"], row["total"]) for row in rows}

    def students(self) -> List[str]:
        """
        Студенты, встречающиеся в журнале.

        :return: отсортированный список идентификаторов
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT student FROM sessions ORDER BY student"
            ).fetchall()
        return [row["student"] for row in rows]

    # ВЫГРУЗКА
    def export_csv(self, directory: Path) -> Tuple[Path, ...]:
        """
        Выгрузить журнал в CSV для анализа.

        CSV --- формат ВЫГРУЗКИ, а не хранения: одновременная дописка в CSV при
        сдаче потоком бьёт строки, и транзакций в нём нет (§ «Решено» в
        ``docs/storage.md``).

        :param directory: каталог для файлов выгрузки; создаётся при необходимости

        :return: пути созданных файлов
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        issues_path = directory / "issues.csv"
        attempts_path = directory / "attempts.csv"

        with issues_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("id", "session_id", "student", "task_code", "seed",
                             "content_version", "created_at"))
            for item in self.issues():
                writer.writerow((item.id, item.session_id, item.student,
                                 item.task_code, item.seed, item.content_version,
                                 item.created_at))

        with attempts_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("id", "issue_id", "student", "task_code", "answer",
                             "verdict", "content_version", "created_at", "details"))
            for attempt in self.attempts():
                writer.writerow((
                    attempt.id, attempt.issue_id, attempt.student,
                    attempt.task_code, attempt.answer, attempt.verdict.value,
                    attempt.content_version, attempt.created_at,
                    json.dumps(dict(attempt.details), ensure_ascii=False),
                ))
        return (issues_path, attempts_path)
