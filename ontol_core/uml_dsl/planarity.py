"""Проверка планарности графа диаграммы (NetworkX) + планарная раскладка.

Вершины — классификаторы, рёбра — связи (обобщения, ассоциации, зависимости,
реализации). Петли игнорируем, кратные рёбра схлопываем -> простой
неориентированный граф.

- Граф планарен -> координаты вершин без пересечений рёбер (планарное вложение,
  ``nx.planar_layout``), масштабированные так, чтобы рамки классов не налезали.
- Граф НЕ планарен -> по теореме Куратовского граф содержит подграф, гомеоморфный
  ``K5`` (полный на 5 вершинах) либо ``K3,3`` (двудольный на 6). Тип определяется
  числом «узловых» вершин (степени ≥ 3): 5 -> ``K5``, 6 -> ``K3,3`` — это верно и
  для подразбиений, где рёбра поделены промежуточными вершинами степени 2.

Большой граф может содержать НЕСКОЛЬКО таких подграфов-нарушителей. Мы находим
их жадно: получаем один контрпример (алгоритм Хопкрофта - Тарьяна), удаляем 
одно его ребро, чтобы разрушить именно этот подграф, и повторяем
проверку — пока граф не станет планарным (или до предела ``_MAX_OBSTRUCTIONS``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import networkx as nx

from .diagram import ClassDiagram, ClassPosition

MARGIN = 40
_GAP = 70  # мин. зазор между рамками классов в планарной раскладке, px
_MAX_OBSTRUCTIONS = 12  # предохранитель от разрастания отчёта для "очень" непланарных графов

_KIND_TEXT = {
    'K5': 'полный граф на 5 вершинах (K5)',
    'K3,3': 'двудольный граф на 6 вершинах (K3,3)',
}


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русский выбор формы слова по числу (1 подграф / 2 подграфа / 5 подграфов)."""
    if 11 <= n % 100 <= 14:
        return many
    d = n % 10
    if d == 1:
        return one
    if 2 <= d <= 4:
        return few
    return many


@dataclass
class Obstruction:
    """Один подграф-нарушитель планарности (гомеоморфный K5 или K3,3)."""

    kind: Optional[str]  # 'K5' | 'K3,3' | None (если не удалось классифицировать)
    labels: List[str]  # узловые классы подграфа (5 для K5, 6 для K3,3)

    def describe(self) -> str:
        what = _KIND_TEXT.get(self.kind, 'подграф Куратовского')
        classes = ', '.join(self.labels) if self.labels else '—'
        return f'{what}: {classes}'


@dataclass
class PlanarityResult:
    is_planar: bool
    # Планарные позиции классов (если планарен) — пиксели, top-left.
    positions: Dict[str, ClassPosition] = field(default_factory=dict)
    # Все найденные подграфы-нарушители (если не планарен).
    obstructions: List[Obstruction] = field(default_factory=list)

    # Агрегаты для обратной совместимости и подсветки на фронте

    @property
    def kind(self) -> Optional[str]:
        """Тип первого (основного) подграфа-нарушителя."""
        return self.obstructions[0].kind if self.obstructions else None

    @property
    def labels(self) -> List[str]:
        """Объединение классов всех подграфов-нарушителей (для красной подсветки)."""
        out: List[str] = []
        for o in self.obstructions:
            for label in o.labels:
                if label not in out:
                    out.append(label)
        return out

    def warning(self) -> Optional[str]:
        """Человекочитаемое предупреждение для автора TDL (или None, если ок)."""
        if self.is_planar or not self.obstructions:
            return None
        tail = 'Диаграмма построена как есть (возможны пересечения рёбер).'
        n = len(self.obstructions)
        if n == 1:
            o = self.obstructions[0]
            what = _KIND_TEXT.get(o.kind, 'подграф Куратовского')
            classes = ', '.join(o.labels) if o.labels else '—'
            return (
                f'Граф диаграммы не планарен: содержит {what}. '
                f'Классы-нарушители: {classes}. {tail}'
            )
        word = _plural(n, 'подграф', 'подграфа', 'подграфов')
        items = '; '.join(
            f'{i}) {o.describe()}' for i, o in enumerate(self.obstructions, 1)
        )
        return (
            f'Граф диаграммы не планарен: найдено {n} {word} Куратовского — '
            f'{items}. {tail}'
        )


def _build_graph(diagram: ClassDiagram) -> nx.Graph:
    known = diagram.classifiers
    g = nx.Graph()  # простой неориентированный: кратные рёбра схлопываются
    g.add_nodes_from(known.keys())

    def link(a: str, b: str) -> None:
        if a != b and a in known and b in known:  # петли игнорируем
            g.add_edge(a, b)

    for gen in diagram.generalizations:
        link(gen.specific.name, gen.general.name)
    for dep in diagram.dependencies:
        link(dep.client.name, dep.supplier.name)
    for real in diagram.realizations:
        link(real.implementer.name, real.interface_.name)
    for assoc in diagram.associations:
        if assoc.is_binary():
            link(assoc.ends[0].participant.name, assoc.ends[1].participant.name)

    return g


def _planar_positions(
    diagram: ClassDiagram, graph: nx.Graph
) -> Dict[str, ClassPosition]:
    raw = nx.planar_layout(graph)  # {name: array([x, y])} в диапазоне ~[-1, 1]
    names = list(raw.keys())

    # Масштаб: минимальное расстояние между центрами должно быть не меньше
    # (макс. габарит рамки + зазор), чтобы боксы не перекрывались.
    max_dim = max(
        (max(diagram.classifiers[n].get_box_size()) for n in names),
        default=120.0,
    )
    min_raw = None
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            (ax, ay), (bx, by) = raw[names[i]], raw[names[j]]
            d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            if d > 1e-9 and (min_raw is None or d < min_raw):
                min_raw = d
    scale = (max_dim + _GAP) / min_raw if min_raw else 1.0

    xs = [float(raw[n][0]) * scale for n in names]
    ys = [float(raw[n][1]) * scale for n in names]
    min_x, min_y = (min(xs) if xs else 0.0), (min(ys) if ys else 0.0)

    positions: Dict[str, ClassPosition] = {}
    for name in names:
        w, h = diagram.classifiers[name].get_box_size()
        cx = float(raw[name][0]) * scale - min_x + MARGIN
        cy = float(raw[name][1]) * scale - min_y + MARGIN
        positions[name] = ClassPosition(
            classifier_name=name, x=cx - w / 2, y=cy - h / 2, width=w, height=h
        )
    return positions


def _classify(kuratowski: nx.Graph) -> tuple[Optional[str], List[str]]:
    """Тип подграфа по числу «узловых» вершин (степени ≥ 3).

    Контрпример от NetworkX — подразбиение K5 или K3,3: рёбра могут быть поделены
    промежуточными вершинами степени 2 (цепочки классов). Поэтому считаем не все
    вершины, а только узловые: 5 -> K5 (степени 4), 6 -> K3,3 (степени 3).
    """
    branch = [n for n in kuratowski.nodes if kuratowski.degree(n) >= 3]
    kind = {5: 'K5', 6: 'K3,3'}.get(len(branch))
    return kind, sorted(str(n) for n in branch)


def _pick_edge(cert: nx.Graph) -> Optional[tuple[str, str]]:
    """Ребро контрпримера, удаление которого надёжнее всего разрушает подграф."""
    branch = {n for n in cert.nodes if cert.degree(n) >= 3}
    for u, v in cert.edges():
        if u in branch and v in branch:
            return (u, v)
    return next(iter(cert.edges()), None)


def _find_obstructions(graph: nx.Graph) -> List[Obstruction]:
    """Жадно извлечь все подграфы-нарушители (гомеоморфные K5/K3,3)."""
    found: List[Obstruction] = []
    seen: set[frozenset[str]] = set()  # чтобы не дублировать один и тот же набор
    h = graph.copy()
    while len(found) < _MAX_OBSTRUCTIONS:
        is_planar, cert = nx.check_planarity(h, counterexample=True)
        if is_planar or cert is None:
            break
        kind, labels = _classify(cert)
        key = frozenset(labels)
        if key not in seen:
            seen.add(key)
            found.append(Obstruction(kind=kind, labels=labels))
        edge = _pick_edge(cert)
        if edge is None:  # вырожденный случай — выходим, чтобы не зациклиться
            break
        h.remove_edge(*edge)
    return found


def analyze(diagram: ClassDiagram) -> PlanarityResult:
    graph = _build_graph(diagram)
    if nx.check_planarity(graph, counterexample=False)[0]:
        # planar_layout может не справиться с несвязным графом — тогда без
        # планарных позиций (рендер откатится на graphviz-раскладку).
        try:
            positions = _planar_positions(diagram, graph)
        except Exception:  # noqa: BLE001
            positions = {}
        return PlanarityResult(is_planar=True, positions=positions)
    return PlanarityResult(is_planar=False, obstructions=_find_obstructions(graph))
