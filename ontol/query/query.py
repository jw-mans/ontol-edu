"""
Запросы к путям над помеченным графом ONTOL-модели (RPQ с узловыми атомами).

Запрос --- регулярное выражение над метками рёбер И ИМЕНОВАННЫМИ УЗЛАМИ:

    gen               одно ребро наследования
    gen+              один или более (собственные предки)
    gen*              ноль или более
    dep gen*          зависимость, затем сколько угодно наследований
    (comp | aggr)+    композиция или агрегация, один или более раз
    instanceOf        ребро-стереотип зависимости «instanceOf»

Узловой атом (начинается с ``@``) не потребляет ребро, а ПРОВЕРЯЕТ текущий узел ---
так узлы становятся именованными в самом паттерне (чего раньше язык не учитывал):

    @Statement        узел с именем ``Statement`` (или коротким именем до `` : ``)
    @kind=theorem     узел со слотом ``kind`` равным ``theorem``
    @level=2          узел со слотом ``level`` равным ``2``
    @meta=Definition  узел, чей метакласс (сосед по ``instanceOf``) --- ``Definition``
    @meta=Concept requires @level=1
                      понятие, ребро requires, зависимость уровня 1

Движок --- произведение графа с автоматом запроса (классический способ вычисления RPQ).
Узловой атом --- эпсилон-переход, разрешённый лишь если узел проходит проверку.
Возвращает достижимые вершины / пары / наличие цикла.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .graph import LabeledGraph

# NFA: (стартовое состояние, принимающее состояние, переходы state -> [(метка|None, state)]).
NFA = Tuple[int, int, Dict[int, List[Tuple[Optional[str], int]]]]
Pattern = Union[str, tuple]


# разбор регэкспа над метками

def _tokenize(text: str) -> List[str]:
    """
    Разбить текст запроса на токены (метки, узловые атомы и операторы).

    :param text: текст паттерна

    :return: список токенов

    :raises ValueError: недопустимый символ
    """
    toks: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()*+?|@=":
            toks.append(ch)
            i += 1
        elif ch.isalnum() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            toks.append(text[i:j])
            i = j
        else:
            raise ValueError(f"Недопустимый символ в запросе: {ch!r}")
    return toks


def parse_pattern(text: str) -> tuple:
    """
    Разобрать паттерн запроса (регэксп над метками + узловые атомы) в AST-кортежи.

    :param text: текст паттерна (напр. ``"gen+ @Statement"``)

    :return: AST паттерна (вложенные кортежи ``lbl``/``node``/``seq``/``alt``/...)

    :raises ValueError: синтаксическая ошибка в паттерне
    """
    toks = _tokenize(text)
    pos = [0]

    def peek():
        """Текущий токен без сдвига (или ``None`` в конце)."""
        return toks[pos[0]] if pos[0] < len(toks) else None

    def eat():
        """Взять текущий токен и сдвинуться вперёд."""
        t = toks[pos[0]]
        pos[0] += 1
        return t

    _SPECIAL = {"(", ")", "*", "+", "?", "|", "@", "="}

    def atom():
        """Разобрать атом: скобки, узловой атом ``@...`` или метку ребра."""
        t = peek()
        if t == "(":
            eat()
            node = alt()
            if peek() != ")":
                raise ValueError("Ожидалась ')'")
            eat()
            return node
        if t == "@":  # узловой атом: @Имя  или  @слот=значение
            eat()
            first = peek()
            if first is None or first in _SPECIAL:
                raise ValueError("Ожидалось имя узла/слота после '@'")
            first = eat()
            if peek() == "=":
                eat()
                val = peek()
                if val is None or val in _SPECIAL:
                    raise ValueError("Ожидалось значение слота после '='")
                return ("node", first, eat())        # @слот=значение
            return ("node", None, first)             # @имя
        if t is None or t in ")*+?|=":
            raise ValueError(f"Ожидалась метка или узел, найдено {t!r}")
        return ("lbl", eat())

    def postfix():
        """Атом с постфиксными кванторами ``*``/``+``/``?``."""
        node = atom()
        while peek() in ("*", "+", "?"):
            op = eat()
            node = {"*": "star", "+": "plus", "?": "opt"}[op], node
        return node

    def seq():
        """Последовательность (конкатенация) постфиксных выражений."""
        node = postfix()
        while peek() is not None and peek() not in (")", "|"):
            node = ("seq", node, postfix())
        return node

    def alt():
        """Альтернатива ``|`` последовательностей."""
        node = seq()
        while peek() == "|":
            eat()
            node = ("alt", node, seq())
        return node

    node = alt()
    if pos[0] != len(toks):
        raise ValueError("Лишние символы в запросе")
    return node


# компиляция AST в NFA (конструкция Томпсона)

def _compile(ast: tuple) -> NFA:
    """
    Скомпилировать AST паттерна в НКА (конструкция Томпсона).

    :param ast: AST паттерна из :func:`parse_pattern`

    :return: НКА ``(старт, приём, переходы)``

    :raises ValueError: неизвестный узел паттерна
    """
    trans: Dict[int, List[Tuple[Optional[str], int]]] = {}
    counter = [0]

    def st() -> int:
        """Создать новое состояние НКА и вернуть его номер."""
        s = counter[0]
        counter[0] += 1
        trans[s] = []
        return s

    def build(node: tuple) -> Tuple[int, int]:
        """Построить фрагмент НКА для узла AST; вернуть ``(вход, выход)``."""
        kind = node[0]
        if kind == "lbl":
            a, b = st(), st()
            trans[a].append((node[1], b))
            return a, b
        if kind == "node":
            a, b = st(), st()
            trans[a].append((("node", node[1], node[2]), b))
            return a, b
        if kind == "eps":
            a, b = st(), st()
            trans[a].append((None, b))
            return a, b
        if kind == "seq":
            a1, b1 = build(node[1])
            a2, b2 = build(node[2])
            trans[b1].append((None, a2))
            return a1, b2
        if kind == "alt":
            a, b = st(), st()
            a1, b1 = build(node[1])
            a2, b2 = build(node[2])
            trans[a] += [(None, a1), (None, a2)]
            trans[b1].append((None, b))
            trans[b2].append((None, b))
            return a, b
        if kind == "star":
            a, b = st(), st()
            a1, b1 = build(node[1])
            trans[a] += [(None, a1), (None, b)]
            trans[b1] += [(None, a1), (None, b)]
            return a, b
        if kind == "plus":
            return build(("seq", node[1], ("star", node[1])))
        if kind == "opt":
            return build(("alt", node[1], ("eps",)))
        raise ValueError(f"Неизвестный узел паттерна: {node!r}")

    start, accept = build(ast)
    return start, accept, trans


def _to_nfa(pattern: Pattern) -> NFA:
    """
    Привести паттерн (строку или AST) к НКА.

    :param pattern: текст паттерна или уже разобранный AST-кортеж

    :return: НКА ``(старт, приём, переходы)``
    """
    if isinstance(pattern, str):
        pattern = parse_pattern(pattern)
    return _compile(pattern)


# вычисление RPQ (произведение графа с автоматом)

def _node_matches(g: LabeledGraph, v: str, key: Optional[str], value: str) -> bool:
    """
    Проверить узел на соответствие узловому атому.

    :param g: помеченный граф
    :param v: имя узла
    :param key: ключ проверки: 
        - ``None`` --- по имени, 
        - ``"meta"`` --- по метаклассу,
        - иначе --- по слоту с таким именем
    :param value: ожидаемое значение

    :return: ``True``, если узел удовлетворяет условию
    """
    if key is None:
        return v == value or v.split(" : ", 1)[0] == value
    if key == "meta":
        m = g.one(v, "instanceOf")
        return m is not None and m.split(" : ", 1)[0] == value
    slot = g.slot(v, key)
    return slot is not None and str(slot) == value


def _reach_from(g: LabeledGraph, src: str, nfa: NFA) -> Set[str]:
    """
    Вершины графа, достижимые из ``src`` по пути, принимаемому автоматом
    (обход произведения графа с НКА).

    :param g: помеченный граф
    :param src: стартовая вершина
    :param nfa: НКА паттерна

    :return: множество вершин, где НКА в принимающем состоянии
    """
    start, accept, trans = nfa
    seen: Set[Tuple[str, int]] = {(src, start)}
    stack = [(src, start)]
    result: Set[str] = set()
    while stack:
        v, q = stack.pop()
        if q == accept:
            result.add(v)
        for lab, q2 in trans[q]:
            if lab is None:
                nxt = (v, q2)
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
            elif isinstance(lab, tuple) and lab[0] == "node":
                if _node_matches(g, v, lab[1], lab[2]):
                    nxt = (v, q2)
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            else:
                for elab, w in g.out(v):
                    if elab == lab:
                        nxt = (w, q2)
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
    return result


def rpq_reachable(g: LabeledGraph, src: str, pattern: Pattern,
                  dst: Optional[str] = None) -> Union[bool, Set[str]]:
    """
    Достижимость по паттерну из ``src``.

    :param g: помеченный граф
    :param src: стартовая вершина
    :param pattern: паттерн (строка или AST)
    :param dst: если задан --- проверить достижимость именно этой вершины

    :return: ``True``/``False`` при заданном ``dst``; иначе --- множество всех
        достижимых по паттерну вершин
    """
    reached = _reach_from(g, src, _to_nfa(pattern))
    if dst is not None:
        return dst in reached
    return reached


def rpq(g: LabeledGraph, pattern: Pattern) -> Set[Tuple[str, str]]:
    """
    Все пары ``(источник, приёмник)``, соединённые путём по паттерну.

    :param g: помеченный граф
    :param pattern: паттерн (строка или AST)

    :return: множество пар вершин
    """
    nfa = _to_nfa(pattern)
    pairs: Set[Tuple[str, str]] = set()
    for src in g.nodes:
        for dst in _reach_from(g, src, nfa):
            pairs.add((src, dst))
    return pairs


def nodes(g: LabeledGraph, pattern: Pattern) -> Set[str]:
    """
    Узлы-приёмники паттерна --- удобно для чисто узловых запросов (``@meta=Definition``).

    :param g: помеченный граф
    :param pattern: паттерн (строка или AST)

    :return: множество узлов-приёмников
    """
    return {d for _s, d in rpq(g, pattern)}


# удобные обёртки

def reachable_set(g: LabeledGraph, src: str, labels: Union[str, Sequence[str]]) -> Set[str]:
    """
    Вершины, достижимые из ``src`` по одному или более рёбрам с указанными метками.

    :param g: помеченный граф
    :param src: стартовая вершина
    :param labels: метка или список меток (образуют паттерн ``(l1 | l2 | ...)+``)

    :return: множество достижимых вершин
    """
    if isinstance(labels, str):
        labels = [labels]
    pat = "(" + " | ".join(labels) + ")+"
    return _reach_from(g, src, _to_nfa(pat))


def ancestors(g: LabeledGraph, node: str) -> Set[str]:
    """
    Собственные предки узла по наследованию (пути ``gen+``).

    :param g: помеченный граф
    :param node: узел-потомок

    :return: множество предков (без самого узла)
    """
    return _reach_from(g, node, _to_nfa("gen+")) - {node}


def descendants(g: LabeledGraph, node: str) -> Set[str]:
    """
    Потомки узла по наследованию: ``X``, у которых ``X gen+ node``.

    :param g: помеченный граф
    :param node: узел-предок

    :return: множество потомков
    """
    nfa = _to_nfa("gen+")
    return {x for x in g.nodes if x != node and node in _reach_from(g, x, nfa)}


def find_cycles(g: LabeledGraph, label: str) -> List[str]:
    """
    Вершины, лежащие на цикле из рёбер метки ``label`` (``v label+ v``).

    Для метки ``gen`` это классы в цикле наследования (некорректная онтология).

    :param g: помеченный граф
    :param label: метка рёбер

    :return: отсортированный список вершин на цикле
    """
    nfa = _to_nfa(f"{label}+")
    return sorted(v for v in g.nodes if v in _reach_from(g, v, nfa))


def has_cycle(g: LabeledGraph, label: str) -> bool:
    """
    Есть ли цикл из рёбер данной метки.

    :param g: помеченный граф
    :param label: метка рёбер

    :return: ``True``, если существует цикл
    """
    return bool(find_cycles(g, label))


# предикаты на узлы и запрос с фильтрами концов

NodePred = "Callable[[str], bool]"


def by_stereotype(g: LabeledGraph, stereotype: str):
    """
    Построить предикат «узел имеет заданный стереотип».

    :param g: помеченный граф
    :param stereotype: искомый стереотип

    :return: предикат ``node -> bool``
    """
    return lambda n: g.node_attrs.get(n, {}).get("stereotype") == stereotype


def is_abstract(g: LabeledGraph):
    """
    Построить предикат «узел --- абстрактный классификатор».

    :param g: помеченный граф

    :return: предикат ``node -> bool``
    """
    return lambda n: bool(g.node_attrs.get(n, {}).get("abstract"))


def name_contains(substr: str):
    """
    Построить предикат «имя узла содержит подстроку».

    :param substr: искомая подстрока

    :return: предикат ``node -> bool``
    """
    return lambda n: substr in n


def has_attribute(g: LabeledGraph, attr: str):
    """
    Построить предикат «у классификатора-узла есть атрибут с таким именем».

    :param g: помеченный граф
    :param attr: имя атрибута

    :return: предикат ``node -> bool``
    """
    return lambda n: attr in (g.node_attrs.get(n, {}).get("attributes") or [])


def select(g: LabeledGraph, pred) -> Set[str]:
    """
    Узлы, удовлетворяющие предикату.

    :param g: помеченный граф
    :param pred: предикат ``node -> bool``

    :return: множество подходящих узлов
    """
    return {n for n in g.nodes if pred(n)}


def _as_pred(spec):
    """
    Привести спецификацию конца пути к предикату.

    :param spec: ``None`` (любой), вызываемый предикат или имя узла (точное совпадение)

    :return: предикат ``node -> bool``
    """
    if spec is None:
        return lambda n: True
    if callable(spec):
        return spec
    return lambda n: n == spec


def query(g: LabeledGraph, pattern: Pattern, src=None, dst=None) -> Set[Tuple[str, str]]:
    """
    Пары ``(источник, цель)`` по паттерну с фильтрами концов.

    Позволяет запросы вида «из абстрактных классов по ``gen+`` в узел со стереотипом
    enumeration».

    :param g: помеченный граф
    :param pattern: паттерн (строка или AST)
    :param src: фильтр источника: имя узла, предикат ``node -> bool`` или ``None`` (любой)
    :param dst: фильтр цели: имя узла, предикат ``node -> bool`` или ``None`` (любой)

    :return: множество пар ``(источник, цель)``, прошедших фильтры
    """
    sp, dp = _as_pred(src), _as_pred(dst)
    nfa = _to_nfa(pattern)
    pairs: Set[Tuple[str, str]] = set()
    for s in g.nodes:
        if not sp(s):
            continue
        for d in _reach_from(g, s, nfa):
            if dp(d):
                pairs.add((s, d))
    return pairs
