#!/usr/bin/env python3
"""
TDL → SVG: чтение файла .tdl, разбор, сборка модели, рендер в SVG.
Запуск: python -m uml_dsl.tdl_run <файл.tdl> [выход.svg|выход.png]
       или из корня: python -m uml_dsl.tdl_run examples/tdl/basic/example.tdl
       для PNG: python -m uml_dsl.tdl_run examples/tdl/basic/example.tdl out.png
"""
from __future__ import annotations

import sys
from pathlib import Path

# Корень проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uml_dsl.tdl_lexer import lex, LexerError
from uml_dsl.tdl_parser import parse_tdl, ParseError
from uml_dsl.tdl_build import build_diagram
from uml_dsl.graphviz_render import diagram_to_graphviz_svg


def tdl_to_svg(
    tdl_text: str,
    width: int = 900,
    height: int = 500,
    theme: str = "light",
) -> str:
    tokens = lex(tdl_text)
    doc = parse_tdl(tokens)
    diagram = build_diagram(doc)
    diagram.validate_all()
    return diagram_to_graphviz_svg(diagram, theme=theme)


def tdl_to_svg_analyzed(tdl_text: str) -> tuple[str, list[str], dict | None]:
    """TDL → (SVG, warnings, planarity) с проверкой планарности.

    Планарен → раскладываем без пересечений рёбер (планарное вложение), planarity
    = None. Не планарен → рендерим как есть (graphviz) и возвращаем
    ``planarity = {kind, labels, message, subgraphs, count}``: ``kind`` — тип
    основного подграфа, ``labels`` — объединение классов всех подграфов-нарушителей
    (для красной подсветки), ``subgraphs`` — разбивка по каждому подграфу
    (``{kind, labels}``), ``count`` — их число.
    """
    from uml_dsl.planarity import analyze

    tokens = lex(tdl_text)
    doc = parse_tdl(tokens)
    diagram = build_diagram(doc)
    diagram.validate_all()

    result = analyze(diagram)
    planarity: dict | None = None
    if result.is_planar and result.positions:
        diagram.positions = result.positions
        diagram.manual_layout = True
    elif not result.is_planar:
        planarity = {
            'kind': result.kind,
            'labels': result.labels,
            'message': result.warning(),
            'subgraphs': [
                {'kind': o.kind, 'labels': o.labels} for o in result.obstructions
            ],
            'count': len(result.obstructions),
        }

    return diagram_to_graphviz_svg(diagram), [], planarity


def main() -> int:
    if len(sys.argv) < 2:
        print("Использование: python -m uml_dsl.tdl_run <файл.tdl> [выход.svg|выход.png]", file=sys.stderr)
        return 1
    tdl_path = Path(sys.argv[1])
    if not tdl_path.is_absolute():
        tdl_path = (Path.cwd() / tdl_path).resolve()
    if not tdl_path.exists():
        print(f"Файл не найден: {tdl_path}", file=sys.stderr)
        return 1
    out_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else tdl_path.with_suffix(".svg")

    try:
        text = tdl_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Ошибка чтения: {e}", file=sys.stderr)
        return 1

    try:
        svg = tdl_to_svg(text)
    except LexerError as e:
        print(f"Ошибка лексера: {e}", file=sys.stderr)
        return 1
    except ParseError as e:
        print(f"Ошибка парсера: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Ошибка модели: {e}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    suf = out_path.suffix.lower()
    if suf == ".png":
        try:
            from uml_dsl.export import svg_to_png
            svg_to_png(svg, output=out_path)
        except ImportError as e:
            print(f"Для PNG нужен cairosvg: pip install cairosvg. {e}", file=sys.stderr)
            return 1
    elif suf == ".jpg" or suf == ".jpeg":
        try:
            from uml_dsl.export import svg_to_jpg
            svg_to_jpg(svg, output=out_path)
        except ImportError as e:
            print(f"Для JPG нужны cairosvg и Pillow: pip install cairosvg Pillow. {e}", file=sys.stderr)
            return 1
    else:
        out_path.write_text(svg, encoding="utf-8")
    print(f"Сохранено: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
