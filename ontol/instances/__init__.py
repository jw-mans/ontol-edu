"""
Экземпляры классов онтологии как продолжение диаграммы классов.

Коробка-экземпляр в нотации ``имя : Класс`` плюс зависимость «instanceOf»
к классу онтологии; см. :class:`ontol.instances.instances.InstanceDiagram`.
"""
from .instances import (
    InstanceDiagram,
    Slots,
    instance_diagram_to_dot,
    instance_of,
)

__all__ = [
    "InstanceDiagram",
    "Slots",
    "instance_of",
    "instance_diagram_to_dot",
]
