"""
Журнал попыток: запись, чтение, неизменяемость, миграции, выгрузка.

Главное, что здесь проверяется, --- не «данные записались», а свойства, на
которых держится ценность журнала: он только дописывается, хранит ответ в
исходном виде и не знает о контенте ничего, кроме строкового кода.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from discrete.journal import (
    SCHEMA_VERSION,
    Attempt,
    Issue,
    Journal,
    JournalError,
    Verdict,
)


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    """Пустой журнал во временном файле."""
    with Journal(tmp_path / "journal.sqlite3") as item:
        yield item


@pytest.fixture()
def filled(journal: Journal) -> Journal:
    """Журнал с одной сессией, двумя выдачами и тремя попытками."""
    session = journal.start_session("ст-1", "abc123")
    first = journal.issue(session, "гр.10", seed=1, content_version="abc123")
    second = journal.issue(session, "гр.11", seed=2, content_version="abc123")
    journal.record_attempt(first, "граф", Verdict.INCORRECT, "abc123",
                           {"пропущено": ["паросочетание"]})
    journal.record_attempt(first, "граф, паросочетание", Verdict.CORRECT, "abc123")
    journal.record_attempt(second, "", Verdict.SKIPPED, "abc123")
    return journal


# ──────────────────────────── открытие и миграции ────────────────────────────

def test_creates_file_and_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "var" / "nested" / "journal.sqlite3"
    with Journal(path):
        pass
    assert path.is_file()


def test_migrate_is_idempotent(journal: Journal) -> None:
    assert journal.migrate() == SCHEMA_VERSION
    assert journal.migrate() == SCHEMA_VERSION


def test_reopening_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    with Journal(path) as first:
        session = first.start_session("ст-1")
        first.issue(session, "гр.1", seed=7)
    with Journal(path) as second:
        assert [item.task_code for item in second.issues()] == ["гр.1"]


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    """
    База, созданная более новой версией кода, не должна молча открываться:
    иначе старый код запишет в неё данные по устаревшей схеме.
    """
    path = tmp_path / "journal.sqlite3"
    with Journal(path):
        pass
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.commit()
    connection.close()

    with pytest.raises(JournalError, match="более новой версией"):
        Journal(path)


# ──────────────────────────── запись ────────────────────────────

def test_records_session_issue_and_attempt(journal: Journal) -> None:
    session = journal.start_session("ст-1", "abc123")
    issue = journal.issue(session, "гр.10", seed=42, content_version="abc123")
    attempt = journal.record_attempt(issue, "граф", Verdict.CORRECT, "abc123")
    assert (session, issue, attempt) == (1, 1, 1)


def test_answer_is_stored_verbatim(journal: Journal) -> None:
    """
    Ответ хранится в исходном виде, а не только как вердикт: после исправления
    ошибки в контенте старые ответы должны поддаваться перепроверке.
    """
    session = journal.start_session("ст-1")
    issue = journal.issue(session, "гр.10", seed=1)
    verbatim = "  граф,  ПАРОСОЧЕТАНИЕ ,, лишнее\n"
    journal.record_attempt(issue, verbatim, Verdict.PARTIAL)
    assert journal.attempts()[0].answer == verbatim


def test_details_round_trip_as_json(journal: Journal) -> None:
    session = journal.start_session("ст-1")
    issue = journal.issue(session, "гр.10", seed=1)
    details = {"пропущено": ["граф"], "лишние": [], "класс": "транзитивность"}
    journal.record_attempt(issue, "ответ", Verdict.INCORRECT, details=details)
    assert journal.attempts()[0].details == details


def test_unserialisable_details_are_refused(journal: Journal) -> None:
    session = journal.start_session("ст-1")
    issue = journal.issue(session, "гр.10", seed=1)
    with pytest.raises(JournalError, match="не сериализуется"):
        journal.record_attempt(issue, "ответ", Verdict.CORRECT,
                               details={"объект": object()})


def test_attempt_for_unknown_issue_is_refused(journal: Journal) -> None:
    with pytest.raises(JournalError, match="отклонена базой"):
        journal.record_attempt(999, "ответ", Verdict.CORRECT)


def test_issue_for_unknown_session_is_refused(journal: Journal) -> None:
    with pytest.raises(JournalError):
        journal.issue(999, "гр.10", seed=1)


def test_task_code_is_a_plain_string_not_a_reference(journal: Journal) -> None:
    """
    Журнал не знает о контенте: код задачи --- строка без проверок. Запись
    должна остаться читаемой даже после удаления единицы из онтологии.
    """
    session = journal.start_session("ст-1")
    issue = journal.issue(session, "кода-такого-в-контенте-нет", seed=1)
    journal.record_attempt(issue, "ответ", Verdict.CORRECT)
    assert journal.attempts()[0].task_code == "кода-такого-в-контенте-нет"


# ──────────────────────── неизменяемость журнала ────────────────────────

def test_attempts_cannot_be_updated(filled: Journal) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        filled._conn.execute("UPDATE attempts SET verdict = 'correct' WHERE id = 1")


def test_attempts_cannot_be_deleted(filled: Journal) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        filled._conn.execute("DELETE FROM attempts WHERE id = 1")


def test_issues_cannot_be_updated_or_deleted(filled: Journal) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        filled._conn.execute("UPDATE issues SET seed = 999 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        filled._conn.execute("DELETE FROM issues WHERE id = 1")


def test_sessions_cannot_be_deleted(filled: Journal) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        filled._conn.execute("DELETE FROM sessions WHERE id = 1")


def test_session_can_be_finished_once(journal: Journal) -> None:
    """Закрытие сессии --- единственное разрешённое обновление."""
    session = journal.start_session("ст-1")
    journal.finish_session(session)
    with pytest.raises(JournalError, match="уже закрыта"):
        journal.finish_session(session)


def test_finishing_unknown_session_is_refused(journal: Journal) -> None:
    with pytest.raises(JournalError, match="не найдена"):
        journal.finish_session(999)


def test_session_fields_cannot_be_rewritten(journal: Journal) -> None:
    session = journal.start_session("ст-1", "abc123")
    with pytest.raises(sqlite3.IntegrityError, match="только дописывается"):
        journal._conn.execute(
            "UPDATE sessions SET student = 'подмена' WHERE id = ?", (session,))


# ──────────────────────────── чтение ────────────────────────────

def test_attempts_are_returned_in_order(filled: Journal) -> None:
    attempts = filled.attempts()
    assert [item.id for item in attempts] == [1, 2, 3]
    assert all(isinstance(item, Attempt) for item in attempts)
    assert [item.verdict for item in attempts] == [
        Verdict.INCORRECT, Verdict.CORRECT, Verdict.SKIPPED,
    ]


def test_attempts_join_student_and_task(filled: Journal) -> None:
    """Студент и код задачи достаются из связанных таблиц, а не дублируются."""
    attempt = filled.attempts()[0]
    assert attempt.student == "ст-1"
    assert attempt.task_code == "гр.10"


def test_attempts_filtered_by_student_and_task(filled: Journal) -> None:
    assert len(filled.attempts(student="ст-1")) == 3
    assert filled.attempts(student="другой") == []
    assert len(filled.attempts(task_code="гр.10")) == 2
    assert len(filled.attempts(student="ст-1", task_code="гр.11")) == 1


def test_issues_listing(filled: Journal) -> None:
    issues = filled.issues()
    assert [item.task_code for item in issues] == ["гр.10", "гр.11"]
    assert all(isinstance(item, Issue) for item in issues)
    assert issues[0].seed == 1
    assert filled.issues(session_id=999) == []


def test_only_the_seed_is_stored_not_the_variant(filled: Journal) -> None:
    """
    Вариант в журнале не лежит: он воспроизводим по паре «код задачи + сид»
    детерминированным генератором.
    """
    issue = filled.issues()[0]
    assert (issue.task_code, issue.seed) == ("гр.10", 1)


def test_task_stats_counts_correct_and_total(filled: Journal) -> None:
    assert filled.task_stats("ст-1") == {"гр.10": (1, 2), "гр.11": (0, 1)}
    assert filled.task_stats("другой") == {}


def test_students_listing(journal: Journal) -> None:
    journal.start_session("ст-2")
    journal.start_session("ст-1")
    journal.start_session("ст-1")
    assert journal.students() == ["ст-1", "ст-2"]


def test_content_version_is_kept_per_record(filled: Journal) -> None:
    """
    Версия контента нужна, чтобы задним числом понять, на какой версии базы
    студент отвечал.
    """
    assert all(item.content_version == "abc123" for item in filled.attempts())
    assert all(item.content_version == "abc123" for item in filled.issues())


# ──────────────────────────── выгрузка ────────────────────────────

def test_export_csv_writes_both_files(filled: Journal, tmp_path: Path) -> None:
    issues_path, attempts_path = filled.export_csv(tmp_path / "export")
    assert issues_path.is_file() and attempts_path.is_file()

    with attempts_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["student"] == "ст-1"
    assert rows[0]["task_code"] == "гр.10"
    assert rows[0]["verdict"] == "incorrect"
    assert "паросочетание" in rows[0]["details"]


def test_export_creates_directory(filled: Journal, tmp_path: Path) -> None:
    target = tmp_path / "нет" / "такого" / "каталога"
    paths = filled.export_csv(target)
    assert all(path.is_file() for path in paths)
