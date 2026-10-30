"""
ontol --- слои поверх ядра ONTOL (``uml_dsl``).

- :mod:`ontol.query`     --- запросы к путям (RPQ/CFPQ) над диаграммой классов;
- :mod:`ontol.instances` --- объявление экземпляров классов онтологии.

Ядро ``uml_dsl`` лежит в каталоге ``ontol_core/`` и подключается как пакет
верхнего уровня (так его импортируют и собственные модули ядра ---
``uml_dsl.app``, ``uml_dsl.tdl_run``, примеры). Чтобы у модуля была ровно одна
идентичность (иначе pydantic-классы задвоятся и ``isinstance`` начнёт врать),
каталог ядра добавляется в ``sys.path`` здесь, при импорте ``ontol``, --- а не
правкой чужого апстрима.
"""
from __future__ import annotations

import sys
from pathlib import Path

#: Корень репозитория (родитель пакета ``ontol``).
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Каталог с ядром ONTOL: внутри лежит пакет ``uml_dsl``.
ONTOL_CORE = REPO_ROOT / "ontol_core"


def bootstrap_core() -> Path:
    """
    Подключить ядро ONTOL (``uml_dsl``) к ``sys.path``.

    Идемпотентно: повторный вызов ничего не меняет. Вызывается автоматически
    при импорте :mod:`ontol`; отдельно пригодится скриптам, которым ядро нужно
    раньше, чем прикладные слои.

    :return: путь к каталогу ядра (``ontol_core``)

    :raises RuntimeError: каталог ядра не найден (неполный клон репозитория)
    """
    if not (ONTOL_CORE / "uml_dsl" / "__init__.py").is_file():
        raise RuntimeError(
            f"Ядро ONTOL не найдено: ожидался пакет 'uml_dsl' в {ONTOL_CORE}"
        )
    path = str(ONTOL_CORE)
    if path not in sys.path:
        sys.path.insert(0, path)
    return ONTOL_CORE


bootstrap_core()

__all__ = ["REPO_ROOT", "ONTOL_CORE", "bootstrap_core"]
