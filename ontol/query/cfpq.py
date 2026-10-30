"""
Контекстно-свободные запросы к путям (CFPQ) над помеченным графом ONTOL.

Запрос задаётся контекстно-свободной грамматикой над метками рёбер: пара вершин
``(u, v)`` в ответе, если между ними есть путь, слово меток которого выводится из
стартового нетерминала. CF-грамматики выражают вложенные/сбалансированные паттерны,
недоступные регулярным запросам (RPQ) --- например «same generation» (общий предок
на одинаковой глубине) через грамматику ``S -> gen S gen_rev | eps``.

Грамматика --- в текстовом виде, нетерминалы определяются левыми частями правил;
остальные символы --- терминалы (метки рёбер). Реализация: нормализация в слабую
нормальную форму Хомского (``A->eps``, ``A->a``, ``A->BC``) и алгоритм Хеллингса.
Реализованы два способа: матричный CFPQ (Азимов--Григорьев) и алгоритм Хеллингса
как эталон/фолбэк при отсутствии numpy/scipy.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from .graph import LabeledGraph

try:
    import numpy as np
    from scipy.sparse import csr_matrix, lil_matrix
    _HAVE_SCIPY = True
except ImportError:  # pragma: no cover
    _HAVE_SCIPY = False

Prod = Tuple[str, Tuple[str, ...]] 


def parse_grammar(text: str) -> Tuple[List[Prod], Set[str]]:
    """
    Разобрать грамматику: строки ``A -> симв симв | ...``; пустая правая часть = eps.

    Возвращает (список правил, множество нетерминалов = левые части).
    """
    prods: List[Prod] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        lhs, sep, rhs = line.partition("->")
        if not sep:
            raise ValueError(f"Нет '->' в правиле: {raw!r}")
        lhs = lhs.strip()
        for alt in rhs.split("|"):
            syms = alt.split()
            if syms == ["eps"]:  # явный эпсилон
                syms = []
            prods.append((lhs, tuple(syms)))
    nonterminals = {lhs for lhs, _ in prods}
    return prods, nonterminals


def _to_weak_cnf(prods: List[Prod], nts: Set[str]) -> List[Prod]:
    """Привести грамматику к слабой ХНФ: правила A->eps, A->a, A->BC."""
    nts = set(nts)
    counter = [0]

    def fresh() -> str:
        counter[0] += 1
        name = f"_B{counter[0]}"
        nts.add(name)
        return name

    # TERM: терминалы в правых частях длины >= 2 заменяем на нетерминалы _T_a -> a
    term_nt: Dict[str, str] = {}
    extra: List[Prod] = []

    def term(sym: str) -> str:
        nt = term_nt.get(sym)
        if nt is None:
            nt = f"_T_{sym}"
            term_nt[sym] = nt
            nts.add(nt)
            extra.append((nt, (sym,)))
        return nt

    p1: List[Prod] = []
    for a, rhs in prods:
        if len(rhs) >= 2:
            rhs = tuple(s if s in nts else term(s) for s in rhs)
        p1.append((a, rhs))
    p1 += extra

    # BIN: правые части длины >= 3 бинаризуем цепочкой свежих нетерминалов
    p2: List[Prod] = []
    for a, rhs in p1:
        if len(rhs) <= 2:
            p2.append((a, rhs))
            continue
        syms = list(rhs)
        cur = a
        while len(syms) > 2:
            b = fresh()
            p2.append((cur, (syms[0], b)))
            cur, syms = b, syms[1:]
        p2.append((cur, (syms[0], syms[1])))

    # UNIT: устраняем единичные правила A->B (B — нетерминал)
    direct = [(a, rhs[0]) for a, rhs in p2 if len(rhs) == 1 and rhs[0] in nts]
    pairs = {(a, a) for a in nts}
    changed = True
    while changed:
        changed = False
        for a, b in list(pairs):
            for x, y in direct:
                if x == b and (a, y) not in pairs:
                    pairs.add((a, y))
                    changed = True
    nonunit = [(a, rhs) for a, rhs in p2 if not (len(rhs) == 1 and rhs[0] in nts)]
    result = {(a, rhs) for a, b in pairs for x, rhs in nonunit if x == b}
    return list(result)


def _classify(cnf: List[Prod]):
    """Разложить правила WCNF на eps / терминальные / бинарные и множество нетерминалов."""
    eps_nt: Set[str] = set()
    term: Dict[str, List[str]] = {}          # метка -> [A]  (A -> метка)
    binary: List[Tuple[str, str, str]] = []  # (A, B, C)     (A -> B C)
    nts: Set[str] = set()
    for a, rhs in cnf:
        nts.add(a)
        if len(rhs) == 0:
            eps_nt.add(a)
        elif len(rhs) == 1:
            term.setdefault(rhs[0], []).append(a)
        else:
            b, c = rhs
            binary.append((a, b, c))
            nts.update((b, c))
    return eps_nt, term, binary, nts


def cfpq(g: LabeledGraph, grammar: str, start: Optional[str] = None,
         method: str = "matrix") -> Set[Tuple[str, str]]:
    """
    Пары ``(u, v)``, между которыми есть путь со словом меток из языка грамматики.

    :param g: помеченный граф (для CF-паттернов часто нужен ``with_reverse=True``)
    :param grammar: текст КС-грамматики над метками рёбер
    :param start: стартовый нетерминал (по умолчанию — левая часть первого правила)
    :param method: ``"matrix"`` (матричное умножение) или
        ``"hellings"``. Матричный требует numpy/scipy; при их отсутствии — фолбэк.
    """
    prods, nts = parse_grammar(grammar)
    if start is None:
        start = prods[0][0]
    cnf = _to_weak_cnf(prods, nts)
    if method == "matrix" and _HAVE_SCIPY:
        return _cfpq_matrix(g, cnf, start)
    return _cfpq_hellings(g, cnf, start)


def _cfpq_matrix(g: LabeledGraph, cnf: List[Prod], start: str) -> Set[Tuple[str, str]]:
    """
    Матричный CFPQ (Азимов--Григорьев): для каждого нетерминала --- булева
    разреженная матрица ``T_A``; итеративно ``T_A |= T_B @ T_C`` до неподвижной точки.
    """
    eps_nt, term, binary, nts = _classify(cnf)
    nodes = sorted(g.nodes)
    idx = {name: i for i, name in enumerate(nodes)}
    n = len(nodes)
    if n == 0:
        return set()

    lil = {a: lil_matrix((n, n), dtype=bool) for a in nts}
    for u, lab, v in g.edges:                     # A -> метка
        for a in term.get(lab, ()):
            lil[a][idx[u], idx[v]] = True
    for a in eps_nt:                              # A -> eps
        for i in range(n):
            lil[a][i, i] = True
    mats: Dict[str, csr_matrix] = {a: lil[a].tocsr() for a in nts}

    changed = True
    while changed:                                # T_A |= T_B @ T_C
        changed = False
        for a, b, c in binary:
            product = (mats[b] @ mats[c]).astype(bool)
            if product.nnz == 0:
                continue
            union = (mats[a] + product).astype(bool)
            union.eliminate_zeros()
            if union.nnz != mats[a].nnz:
                mats[a] = union
                changed = True

    if start not in mats:
        return set()
    coo = mats[start].tocoo()
    return {(nodes[i], nodes[j]) for i, j in zip(coo.row.tolist(), coo.col.tolist())}


def _cfpq_hellings(g: LabeledGraph, cnf: List[Prod], start: str) -> Set[Tuple[str, str]]:
    """CFPQ алгоритмом Хеллингса (без numpy/scipy) --- эталон/фолбэк."""
    eps_nt, term_list, binary, _ = _classify(cnf)
    term_prod: Dict[str, Set[str]] = {lab: set(a) for lab, a in term_list.items()}
    bin_left: Dict[str, List[Tuple[str, str]]] = {}   # B -> [(A, C)] для A->B C
    bin_right: Dict[str, List[Tuple[str, str]]] = {}  # C -> [(A, B)] для A->B C
    for a, b, c in binary:
        bin_left.setdefault(b, []).append((a, c))
        bin_right.setdefault(c, []).append((a, b))

    by_first: Dict[Tuple[str, str], Set[str]] = {}
    by_second: Dict[Tuple[str, str], Set[str]] = {}
    wl: deque = deque()

    def add(a: str, u: str, v: str) -> None:
        if v in by_first.setdefault((a, u), set()):
            return
        by_first[(a, u)].add(v)
        by_second.setdefault((a, v), set()).add(u)
        wl.append((a, u, v))

    for a in eps_nt:
        for v in g.nodes:
            add(a, v, v)
    for u, lab, v in g.edges:
        for a in term_prod.get(lab, ()):
            add(a, u, v)

    while wl:
        b, u, v = wl.popleft()
        for a, c in bin_left.get(b, ()):
            for w in list(by_first.get((c, v), ())):
                add(a, u, w)
        for a, c in bin_right.get(b, ()):
            for w in list(by_second.get((c, u), ())):
                add(a, w, v)

    return {(u, v) for (a, u), vs in by_first.items() if a == start for v in vs}
