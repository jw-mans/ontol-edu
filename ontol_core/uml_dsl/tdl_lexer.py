# Лексер TDL (Text Diagram Language)
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class TokenKind(Enum):
    КЛАСС = "КЛАСС"
    ИНТЕРФЕЙС = "ИНТЕРФЕЙС"
    ТИП_ДАННЫХ = "ТИП_ДАННЫХ"
    ШАБЛОН = "ШАБЛОН"
    ПАРАМЕТРЫ = "ПАРАМЕТРЫ"
    ПОДСТАНОВКА = "ПОДСТАНОВКА"
    КЛАСС_АССОЦИАЦИИ = "КЛАСС_АССОЦИАЦИИ"
    ПЕРЕЧИСЛЕНИЕ = "ПЕРЕЧИСЛЕНИЕ"
    КОНЕЦ = "КОНЕЦ"
    АБСТРАКТНЫЙ = "АБСТРАКТНЫЙ"
    АТРИБУТЫ = "АТРИБУТЫ"
    ОПЕРАЦИИ = "ОПЕРАЦИИ"
    ОБОБЩЕНИЕ = "ОБОБЩЕНИЕ"
    АССОЦИАЦИЯ = "АССОЦИАЦИЯ"
    КОМПОЗИЦИЯ = "КОМПОЗИЦИЯ"
    АГРЕГАЦИЯ = "АГРЕГАЦИЯ"
    ЗАВИСИМОСТЬ = "ЗАВИСИМОСТЬ"
    РЕАЛИЗАЦИЯ = "РЕАЛИЗАЦИЯ"
    РАЗМЕЩЕНИЕ = "РАЗМЕЩЕНИЕ"
    ВЫРОВНЯТЬ = "ВЫРОВНЯТЬ"
    РАСПРЕДЕЛИТЬ = "РАСПРЕДЕЛИТЬ"
    СГРУППИРОВАТЬ = "СГРУППИРОВАТЬ"
    ПРИВЯЗАТЬ = "ПРИВЯЗАТЬ"
    ЗАФИКСИРОВАТЬ = "ЗАФИКСИРОВАТЬ"
    ПОВЕРНУТЬ = "ПОВЕРНУТЬ"
    ПО = "ПО"
    ЛЕВОМУ = "ЛЕВОМУ"
    ПРАВОМУ = "ПРАВОМУ"
    ВЕРХУ = "ВЕРХУ"
    НИЗУ = "НИЗУ"
    ГОРИЗОНТАЛИ = "ГОРИЗОНТАЛИ"
    ВЕРТИКАЛИ = "ВЕРТИКАЛИ"
    ШАГ = "ШАГ"
    КАК = "КАК"
    ЛЕВЕЕ = "ЛЕВЕЕ"
    ПРАВЕЕ = "ПРАВЕЕ"
    ВЫШЕ = "ВЫШЕ"
    НИЖЕ = "НИЖЕ"
    В = "В"
    ИМЯ = "ИМЯ"
    ПРОИЗВОДНАЯ = "ПРОИЗВОДНАЯ"
    ПОДСТАНОВОЧНОЕ = "ПОДСТАНОВОЧНОЕ"
    ТОЛЬКО_ЧТЕНИЕ = "только_чтение"
    АБСТРАКТНАЯ = "абстрактная"
    ЗАПРОС = "запрос"
    ЛИСТ = "лист"
    ARROW = "->"
    DASH = "--"
    PLUS = "+"
    MINUS = "-"
    HASH = "#"
    TILDE = "~"
    STAR = "*"
    DOTDOT = ".."
    COMMA = ","
    SEMICOLON = ";"
    COLON = ":"
    EQUALS = "="
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    LBRACE = "{"
    RBRACE = "}"
    IDENT = "IDENT"
    NUMBER = "NUMBER"
    STRING = "STRING"
    EOF = "EOF"


KEYWORDS: Dict[str, TokenKind] = {
    "класс": TokenKind.КЛАСС,
    "интерфейс": TokenKind.ИНТЕРФЕЙС,
    "тип_данных": TokenKind.ТИП_ДАННЫХ,
    "шаблон": TokenKind.ШАБЛОН,
    "параметры": TokenKind.ПАРАМЕТРЫ,
    "подстановка": TokenKind.ПОДСТАНОВКА,
    "класс_ассоциации": TokenKind.КЛАСС_АССОЦИАЦИИ,
    "перечисление": TokenKind.ПЕРЕЧИСЛЕНИЕ,
    "конец": TokenKind.КОНЕЦ,
    "абстрактный": TokenKind.АБСТРАКТНЫЙ,
    "атрибуты": TokenKind.АТРИБУТЫ,
    "операции": TokenKind.ОПЕРАЦИИ,
    "обобщение": TokenKind.ОБОБЩЕНИЕ,
    "ассоциация": TokenKind.АССОЦИАЦИЯ,
    "композиция": TokenKind.КОМПОЗИЦИЯ,
    "агрегация": TokenKind.АГРЕГАЦИЯ,
    "зависимость": TokenKind.ЗАВИСИМОСТЬ,
    "реализация": TokenKind.РЕАЛИЗАЦИЯ,
    "размещение": TokenKind.РАЗМЕЩЕНИЕ,
    "выровнять": TokenKind.ВЫРОВНЯТЬ,
    "распределить": TokenKind.РАСПРЕДЕЛИТЬ,
    "сгруппировать": TokenKind.СГРУППИРОВАТЬ,
    "привязать": TokenKind.ПРИВЯЗАТЬ,
    "зафиксировать": TokenKind.ЗАФИКСИРОВАТЬ,
    "повернуть": TokenKind.ПОВЕРНУТЬ,
    "по": TokenKind.ПО,
    "левому": TokenKind.ЛЕВОМУ,
    "правому": TokenKind.ПРАВОМУ,
    "верху": TokenKind.ВЕРХУ,
    "низу": TokenKind.НИЗУ,
    "горизонтали": TokenKind.ГОРИЗОНТАЛИ,
    "вертикали": TokenKind.ВЕРТИКАЛИ,
    "шаг": TokenKind.ШАГ,
    "как": TokenKind.КАК,
    "левее": TokenKind.ЛЕВЕЕ,
    "правее": TokenKind.ПРАВЕЕ,
    "выше": TokenKind.ВЫШЕ,
    "ниже": TokenKind.НИЖЕ,
    "в": TokenKind.В,
    "имя": TokenKind.ИМЯ,
    "производная": TokenKind.ПРОИЗВОДНАЯ,
    "подстановочное": TokenKind.ПОДСТАНОВОЧНОЕ,
    "только_чтение": TokenKind.ТОЛЬКО_ЧТЕНИЕ,
    "абстрактная": TokenKind.АБСТРАКТНАЯ,
    "запрос": TokenKind.ЗАПРОС,
    "лист": TokenKind.ЛИСТ,
}


@dataclass
class Token:
    kind: TokenKind
    value: Optional[str] = None
    line: int = 0
    column: int = 0


class LexerError(Exception):
    def __init__(self, msg: str, line: int, column: int):
        self.line = line
        self.column = column
        super().__init__(f"{msg} (строка {line}, столбец {column})")


def _is_letter(c: str) -> bool:
    return c.isalpha() or c == "_" or (
        c in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    )


def _is_ident_cont(c: str) -> bool:
    return c.isalnum() or c == "_" or _is_letter(c)


def lex(source: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)
    at_line_start = True

    while i < n:
        start_col = col
        if source[i] in " \t\r\n":
            if source[i] == "\n":
                line += 1
                col = 1
                at_line_start = True
            else:
                at_line_start = False
                col += 1
            i += 1
            continue
        # Комментарий "--" только в начале строки (после пробелов с начала строки)
        if at_line_start and i + 1 < n and source[i : i + 2] == "--":
            while i < n and source[i] != "\n":
                i += 1
                col += 1
            continue
        at_line_start = False
        # Двусимвольный токен "--" (связь) — не в начале строки
        if i + 1 < n and source[i : i + 2] == "--":
            tokens.append(Token(TokenKind.DASH, None, line, start_col))
            i += 2
            col += 2
            continue
        if source[i] == '"':
            i += 1
            col += 1
            buf = []
            while i < n and source[i] != '"':
                if source[i] == "\\" and i + 1 < n:
                    i += 1
                    buf.append(source[i])
                    i += 1
                    col += 2
                else:
                    buf.append(source[i])
                    i += 1
                    col += 1
            if i < n:
                i += 1
                col += 1
            tokens.append(Token(TokenKind.STRING, "".join(buf), line, start_col))
            continue
        if source[i].isdigit():
            buf = []
            while i < n and source[i].isdigit():
                buf.append(source[i])
                i += 1
                col += 1
            tokens.append(Token(TokenKind.NUMBER, "".join(buf), line, start_col))
            continue
        if i + 1 < n:
            two = source[i : i + 2]
            if two == "->":
                tokens.append(Token(TokenKind.ARROW, None, line, start_col))
                i += 2
                col += 2
                continue
            if two == "..":
                tokens.append(Token(TokenKind.DOTDOT, None, line, start_col))
                i += 2
                col += 2
                continue
        single = source[i]
        if single == "+":
            tokens.append(Token(TokenKind.PLUS, None, line, start_col))
            i += 1
            col += 1
            continue
        if single == "-":
            tokens.append(Token(TokenKind.MINUS, None, line, start_col))
            i += 1
            col += 1
            continue
        if single == "#":
            tokens.append(Token(TokenKind.HASH, None, line, start_col))
            i += 1
            col += 1
            continue
        if single == "~":
            tokens.append(Token(TokenKind.TILDE, None, line, start_col))
            i += 1
            col += 1
            continue
        if single == "*":
            tokens.append(Token(TokenKind.STAR, None, line, start_col))
            i += 1
            col += 1
            continue
        for sym, kind in [
            (",", TokenKind.COMMA),
            (";", TokenKind.SEMICOLON),
            (":", TokenKind.COLON),
            ("=", TokenKind.EQUALS),
            ("(", TokenKind.LPAREN),
            (")", TokenKind.RPAREN),
            ("[", TokenKind.LBRACKET),
            ("]", TokenKind.RBRACKET),
            ("{", TokenKind.LBRACE),
            ("}", TokenKind.RBRACE),
        ]:
            if single == sym:
                tokens.append(Token(kind, None, line, start_col))
                i += 1
                col += 1
                break
        else:
            if _is_letter(source[i]):
                buf = []
                while i < n and _is_ident_cont(source[i]):
                    buf.append(source[i])
                    i += 1
                    col += 1
                word = "".join(buf)
                kind = KEYWORDS.get(word.lower())
                if kind is not None:
                    tokens.append(Token(kind, None, line, start_col))
                else:
                    tokens.append(Token(TokenKind.IDENT, word, line, start_col))
                continue
            raise LexerError(f"Неизвестный символ: {source[i]!r}", line, col)

    tokens.append(Token(TokenKind.EOF, None, line, col))
    return tokens
