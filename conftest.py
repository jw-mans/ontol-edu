"""
Бутстрап путей импорта для pytest.

Структура репозитория несимметрична, потому что ядро --- чужой апстрим:

- ``ontol_core/uml_dsl/`` --- ядро ONTOL. Его собственные модули и примеры
  импортируют себя как пакет верхнего уровня (``from uml_dsl.diagram import ...``),
  поэтому в ``sys.path`` должен попасть каталог ``ontol_core/``, а не корень
  репозитория. Правка ядра под нашу структуру запрещена.
- корень репозитория --- для наших пакетов ``ontol`` (и далее ``discrete``,
  ``trainer``).

Оба пути добавляет :func:`ontol.bootstrap_core`, вызываемая при импорте
``ontol``; здесь же корень репозитория кладётся в ``sys.path`` до импорта,
чтобы сам ``import ontol`` стал возможен при любом рабочем каталоге.

Важно, что ядро подключается РОВНО одним способом: если бы ``uml_dsl`` был
импортирован и как ``uml_dsl``, и как ``ontol_core.uml_dsl``, pydantic-классы
задвоились бы, и ``isinstance``/валидаторы начали бы врать на объектах из
«другой» копии.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ontol  # noqa: E402  (импорт после правки sys.path --- это и есть бутстрап)

ontol.bootstrap_core()
