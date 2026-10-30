"""
ONTOL-модель (диаграмма классов) как помеченный ориентированный граф.

Узлы --- имена классификаторов. Рёбра ``(источник, метка, приёмник)`` по типу связи:

- ``gen``   --- обобщение (наследование): 
    specific -> general (потомок -> предок);
- стереотип зависимости (напр. ``instanceOf``, ``use``) либо ``dep`` --- 
    client -> supplier;
- ``real``  --- реализация: 
    реализующий -> интерфейс;
- ``comp``/``aggr`` --- композиция/агрегация: 
    целое -> часть;
- ``assoc`` --- прочая бинарная ассоциация: 
    end0 -> end1.

Ассоциации к связям (полюс --- не классификатор) пропускаются. Ядро ``uml_dsl``
только читается.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

Edge = Tuple[str, str, str]  # (источник, метка, приёмник)


@dataclass
class LabeledGraph:
    """
    Помеченный ориентированный граф: узлы и рёбра с метками.

    ``node_attrs`` хранит свойства классификатора-узла (``stereotype``,
    ``abstract``, ``attributes``) для запросов-предикатов по узлам.
    """
    nodes: Set[str] = field(default_factory=set)
    edges: List[Edge] = field(default_factory=list)
    node_attrs: Dict[str, dict] = field(default_factory=dict)
    _adj: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)

    def add_node(self, name: str, **attrs) -> None:
        """
        Добавить узел (идемпотентно) и обновить его атрибуты.

        :param name: имя узла (классификатора)
        :param attrs: свойства узла (``stereotype``/``abstract``/``attributes``/``slots``)
        """
        self.nodes.add(name)
        self._adj.setdefault(name, [])
        if attrs:
            self.node_attrs.setdefault(name, {}).update(attrs)

    def add_edge(self, src: str, label: str, dst: str) -> None:
        """
        Добавить ребро с меткой (концы создаются при необходимости).

        :param src: источник
        :param label: метка ребра (тип связи/роль)
        :param dst: приёмник
        """
        self.add_node(src)
        self.add_node(dst)
        self.edges.append((src, label, dst))
        self._adj[src].append((label, dst))

    def out(self, node: str) -> List[Tuple[str, str]]:
        """
        Исходящие рёбра узла.

        :param node: имя узла

        :return: список ``(метка, приёмник)``
        """
        return self._adj.get(node, [])

    def out_by(self, node: str, label: str) -> List[str]:
        """
        Соседи узла по ребру с данной меткой (точечный запрос по роли).

        :param node: имя узла
        :param label: метка ребра

        :return: список приёмников
        """
        return [dst for lab, dst in self._adj.get(node, []) if lab == label]

    def one(self, node: str, label: str) -> Optional[str]:
        """
        Единственный сосед по метке (для функциональных ролей).

        :param node: имя узла
        :param label: метка ребра

        :return: первый приёмник либо ``None``
        """
        hits = self.out_by(node, label)
        return hits[0] if hits else None

    def slot(self, node: str, key: str, default=None):
        """
        Значение слота узла (атрибута классификатора).

        :param node: имя узла
        :param key: имя слота
        :param default: значение по умолчанию, если слота нет

        :return: значение слота либо ``default``
        """
        return self.node_attrs.get(node, {}).get("slots", {}).get(key, default)

    def labels(self) -> Set[str]:
        """
        Все встречающиеся метки рёбер.

        :return: множество меток
        """
        return {lab for _, lab, _ in self.edges}


def _aggregation_value(end) -> str:
    """
    Вид агрегации полюса ассоциации.

    :param end: полюс ассоциации (``AssociationEnd``/``AggregationEnd``)

    :return: ``'composition'`` | ``'aggregation'`` | ``'none'``
    """
    agg = getattr(end, "aggregation", None)
    return getattr(agg, "value", "none") if agg is not None else "none"


def diagram_to_graph(diagram, with_reverse: bool = False,
                     role_labels: bool = False) -> LabeledGraph:
    """
    Построить помеченный граф из ONTOL-диаграммы классов.

    :param diagram: диаграмма классов ``uml_dsl.ClassDiagram``
    :param with_reverse: добавить к каждому ребру ``(u, lab, v)`` обратное
        ``(v, lab+"_rev", u)`` --- нужно для CFPQ (напр. «same generation»)
    :param role_labels: помечать ребро обычной ассоциации её ролью (``ends[1].role``)
        вместо ``assoc`` --- так структурные связи модели-интерпретатора
        (``from``/``then``/``else``/``left``/``right`` ...) становятся метками рёбер
        (композиция/агрегация и так помечены ``comp``/``aggr``)

    :return: помеченный ориентированный граф со слотами узлов
    """
    g = LabeledGraph()
    for name, cls in diagram.classifiers.items():
        stereo = getattr(cls, "stereotype", None)
        attrs = getattr(cls, "attributes", []) or []
        g.add_node(
            name,
            stereotype=getattr(stereo, "value", None),
            abstract=bool(getattr(cls, "is_abstract", False)),
            attributes=[a.name for a in attrs],
            slots={a.name: a.initial_value for a in attrs},
        )

    known = set(diagram.classifiers)

    # обобщения: потомок -> предок
    for gen in getattr(diagram, "generalizations", []):
        s, t = gen.specific.name, gen.general.name
        if s in known and t in known:
            g.add_edge(s, "gen", t)

    # зависимости: client -> supplier, метка = стереотип или 'dep'
    for dep in getattr(diagram, "dependencies", []):
        s, t = dep.client.name, dep.supplier.name
        if s in known and t in known:
            stereo = getattr(dep, "stereotype", None)
            label = getattr(stereo, "value", None) or "dep"
            g.add_edge(s, label, t)

    # реализации: реализующий -> интерфейс
    for real in getattr(diagram, "realizations", []):
        s = getattr(real, "implementing_classifier", None)
        t = getattr(real, "interface", None)
        if s in known and t in known:
            g.add_edge(s, "real", t)

    # ассоциации: композиция/агрегация целое->часть; иначе assoc end0->end1
    for assoc in getattr(diagram, "associations", []):
        if len(assoc.ends) != 2:
            continue
        a, b = assoc.ends[0], assoc.ends[1]
        na, nb = a.participant_name, b.participant_name
        if na not in known or nb not in known:
            continue  # ассоциация к связи — пропускаем
        agg_a, agg_b = _aggregation_value(a), _aggregation_value(b)
        if agg_a in ("composition", "aggregation"):
            g.add_edge(na, "comp" if agg_a == "composition" else "aggr", nb)  # целое a -> часть b
        elif agg_b in ("composition", "aggregation"):
            g.add_edge(nb, "comp" if agg_b == "composition" else "aggr", na)  # целое b -> часть a
        elif role_labels and getattr(b, "role", None):
            g.add_edge(na, b.role, nb)  # структурная связь помечена ролью (from/then/left/...)
        else:
            g.add_edge(na, "assoc", nb)

    if with_reverse:
        for src, label, dst in list(g.edges):
            g.add_edge(dst, f"{label}_rev", src)

    return g
