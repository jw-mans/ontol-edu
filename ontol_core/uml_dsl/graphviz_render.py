"""
Graphviz pipeline: ClassDiagram -> DOT -> SVG -> enrich data-* attributes.
"""
from __future__ import annotations

import html
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from .diagram import ClassDiagram, ClassPosition

PX_PER_INCH = 72
MARGIN = 40
DEFAULT_DOT_PATH = r"C:\Program Files\Graphviz\bin\dot.exe"
DEFAULT_SVG_THEME = "light"
SVG_STYLE_DIR = Path(__file__).resolve().parent / "styles"
EDGE_COLOR = "#181818"
EDGE_STROKE_WIDTH = 1.0
EDGE_DASH_ARRAY = "7,7"
EDGE_LABEL_FONT = "sans-serif"
EDGE_LABEL_FONT_SIZE = 13
MULTIPLICITY_ENDPOINT_OFFSET = 16.0
MULTIPLICITY_LINE_GAP = 2.5
MULTIPLICITY_HORIZONTAL_GAP = 8.0
MULTIPLICITY_HORIZONTAL_BASELINE = 16.0
MULTIPLICITY_BASELINE_SHIFT = 4.5

from .enums import AggregationKind

def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)

def _q(value: str) -> str:
    """Quote value for DOT ids/strings."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _normalize_svg_theme(theme: str | None) -> str:
    candidate = (theme or DEFAULT_SVG_THEME).strip().lower()
    if candidate == "default":
        return DEFAULT_SVG_THEME
    if not re.fullmatch(r"[a-z0-9_-]+", candidate):
        return DEFAULT_SVG_THEME
    return candidate


def available_svg_themes() -> list[str]:
    if not SVG_STYLE_DIR.exists():
        return [DEFAULT_SVG_THEME]

    themes = [
        path.stem
        for path in SVG_STYLE_DIR.glob("*.css")
        if re.fullmatch(r"[a-z0-9_-]+", path.stem)
    ]
    themes = [DEFAULT_SVG_THEME] + sorted(
        theme for theme in themes if theme != DEFAULT_SVG_THEME
    )
    return themes or [DEFAULT_SVG_THEME]


def _load_svg_style(theme: str | None) -> tuple[str, str]:
    resolved_theme = _normalize_svg_theme(theme)
    style_path = SVG_STYLE_DIR / f"{resolved_theme}.css"

    if not style_path.exists():
        resolved_theme = DEFAULT_SVG_THEME
        style_path = SVG_STYLE_DIR / f"{resolved_theme}.css"

    if not style_path.exists():
        return resolved_theme, ""

    css = style_path.read_text(encoding="utf-8").replace("]]>", "]]\\>")
    return resolved_theme, (
        f'<style id="uml-theme-{_esc(resolved_theme)}" type="text/css"><![CDATA[\n'
        f"{css}\n"
        f"]]></style>"
    )

def _center(pos: ClassPosition) -> tuple[float, float]:
    return pos.x + pos.width / 2, pos.y + pos.height / 2


def _edge_point(from_pos: ClassPosition, to_pos: ClassPosition) -> tuple[float, float]:
    fx, fy = _center(from_pos)
    tx, ty = _center(to_pos)

    dx = tx - fx
    dy = ty - fy

    if abs(dx) > abs(dy):
        if dx > 0:
            return from_pos.x + from_pos.width, fy
        return from_pos.x, fy

    if dy > 0:
        return fx, from_pos.y + from_pos.height

    return fx, from_pos.y

def _dedupe_points(
    points: list[tuple[float, float]],
    eps: float = 0.5,
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []

    for x, y in points:
        if not result:
            result.append((x, y))
            continue

        px, py = result[-1]
        if abs(px - x) > eps or abs(py - y) > eps:
            result.append((x, y))

    return result


def _box_boundary_towards(
    pos: ClassPosition,
    target: tuple[float, float],
) -> tuple[float, float]:
    cx, cy = _center(pos)
    tx, ty = target

    dx = tx - cx
    dy = ty - cy

    if dx == 0 and dy == 0:
        return cx, cy

    half_w = pos.width / 2
    half_h = pos.height / 2

    if abs(dx) * half_h > abs(dy) * half_w:
        x = pos.x + pos.width if dx > 0 else pos.x
        scale = half_w / abs(dx)
        y = cy + dy * scale
    else:
        y = pos.y + pos.height if dy > 0 else pos.y
        scale = half_h / abs(dy)
        x = cx + dx * scale

    x = max(pos.x, min(pos.x + pos.width, x))
    y = max(pos.y, min(pos.y + pos.height, y))

    return x, y


def _edge_route(
    from_pos: ClassPosition,
    to_pos: ClassPosition,
    route: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    if route and len(route) >= 2:
        points = _dedupe_points(route)

        if len(points) >= 2:
            points[0] = _box_boundary_towards(from_pos, points[1])
            points[-1] = _box_boundary_towards(to_pos, points[-2])
            return _dedupe_points(points)

    return [
        _edge_point(from_pos, to_pos),
        _edge_point(to_pos, from_pos),
    ]

def _points_attr(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _path_attr(d: str) -> str:
    return html.escape(d, quote=True)


def _transform_attr(transform: str) -> str:
    return html.escape(transform, quote=True)


def _dot_command() -> str:
    return shutil.which("dot") or DEFAULT_DOT_PATH


PathSegment = tuple[str, tuple[tuple[float, float], ...]]


def _parse_transform_values(raw: str) -> list[float]:
    return [
        float(value)
        for value in re.split(r"[\s,]+", raw.strip())
        if value
    ]


def _apply_svg_transform(
    point: tuple[float, float],
    transform: str,
) -> tuple[float, float]:
    x, y = point

    for name, raw_values in re.findall(r"(\w+)\(([^)]*)\)", transform):
        values = _parse_transform_values(raw_values)

        if name == "translate":
            x += values[0] if values else 0.0
            y += values[1] if len(values) > 1 else 0.0
        elif name == "scale":
            sx = values[0] if values else 1.0
            sy = values[1] if len(values) > 1 else sx
            x *= sx
            y *= sy
        elif name == "rotate":
            angle = math.radians(values[0] if values else 0.0)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            x, y = x * cos_a - y * sin_a, x * sin_a + y * cos_a

    return x, y


def _tokenize_path(path_d: str) -> list[str]:
    return re.findall(
        r"[MmLlHhVvCcZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?",
        path_d,
    )


def _parse_path(path_d: str) -> tuple[tuple[float, float], list[PathSegment]]:
    tokens = _tokenize_path(path_d)
    idx = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    subpath_start = (0.0, 0.0)
    segments: list[PathSegment] = []

    def has_number() -> bool:
        return idx < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[idx])

    def number() -> float:
        nonlocal idx
        value = float(tokens[idx])
        idx += 1
        return value

    def point(relative: bool = False) -> tuple[float, float]:
        x = number()
        y = number()
        if relative:
            return current[0] + x, current[1] + y
        return x, y

    while idx < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[idx]):
            command = tokens[idx]
            idx += 1

        relative = command.islower()
        upper = command.upper()

        if upper == "M":
            current = point(relative)
            if not segments:
                start = current
            subpath_start = current
            command = "l" if relative else "L"

            while has_number():
                next_point = point(relative)
                segments.append(("L", (current, next_point)))
                current = next_point

        elif upper == "L":
            while has_number():
                next_point = point(relative)
                segments.append(("L", (current, next_point)))
                current = next_point

        elif upper == "H":
            while has_number():
                x = number()
                next_point = (current[0] + x, current[1]) if relative else (x, current[1])
                segments.append(("L", (current, next_point)))
                current = next_point

        elif upper == "V":
            while has_number():
                y = number()
                next_point = (current[0], current[1] + y) if relative else (current[0], y)
                segments.append(("L", (current, next_point)))
                current = next_point

        elif upper == "C":
            while has_number():
                p1 = point(relative)
                p2 = point(relative)
                p3 = point(relative)
                segments.append(("C", (current, p1, p2, p3)))
                current = p3

        elif upper == "Z":
            segments.append(("L", (current, subpath_start)))
            current = subpath_start
            command = ""

        else:
            break

    return start, segments


def _transform_path_d(path_d: str, transform: str) -> str:
    start, segments = _parse_path(path_d)
    start = _apply_svg_transform(start, transform)
    parts = [f"M{start[0]:.1f},{start[1]:.1f}"]

    for command, points in segments:
        transformed = [_apply_svg_transform(point, transform) for point in points]

        if command == "L":
            _, end = transformed
            parts.append(f"L{end[0]:.1f},{end[1]:.1f}")
        elif command == "C":
            _, p1, p2, end = transformed
            parts.append(
                f"C{p1[0]:.1f},{p1[1]:.1f} "
                f"{p2[0]:.1f},{p2[1]:.1f} "
                f"{end[0]:.1f},{end[1]:.1f}"
            )

    return " ".join(parts)


def _format_path(
    start: tuple[float, float],
    segments: list[PathSegment],
) -> str:
    parts = [f"M{start[0]:.1f},{start[1]:.1f}"]

    for command, points in segments:
        if command == "L":
            _, end = points
            parts.append(f"L{end[0]:.1f},{end[1]:.1f}")
        elif command == "C":
            _, p1, p2, end = points
            parts.append(
                f"C{p1[0]:.1f},{p1[1]:.1f} "
                f"{p2[0]:.1f},{p2[1]:.1f} "
                f"{end[0]:.1f},{end[1]:.1f}"
            )

    return " ".join(parts)


def _path_with_endpoint(
    path_d: str | None,
    point: tuple[float, float],
    *,
    at_start: bool,
) -> str | None:
    if not path_d:
        return path_d

    start, segments = _parse_path(path_d)
    if at_start:
        return _format_path(point, segments)

    if not segments:
        return _format_path(point, segments)

    changed_segments = list(segments)
    command, points = changed_segments[-1]
    changed_segments[-1] = (command, (*points[:-1], point))
    return _format_path(start, changed_segments)


def _points_with_endpoint(
    points: list[tuple[float, float]],
    point: tuple[float, float],
    *,
    at_start: bool,
) -> list[tuple[float, float]]:
    if not points:
        return [point]

    changed_points = list(points)
    if at_start:
        changed_points[0] = point
    else:
        changed_points[-1] = point

    return _dedupe_points(changed_points, eps=0.1)


def _cubic_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1.0 - t
    x = (
        mt * mt * mt * p0[0]
        + 3 * mt * mt * t * p1[0]
        + 3 * mt * t * t * p2[0]
        + t * t * t * p3[0]
    )
    y = (
        mt * mt * mt * p0[1]
        + 3 * mt * mt * t * p1[1]
        + 3 * mt * t * t * p2[1]
        + t * t * t * p3[1]
    )
    return x, y


def _flatten_path(
    path_d: str,
    curve_steps: int = 24,
) -> list[tuple[float, float]]:
    start, segments = _parse_path(path_d)
    points = [start]

    for command, segment_points in segments:
        if command == "L":
            points.append(segment_points[-1])
        elif command == "C":
            p0, p1, p2, p3 = segment_points
            for step in range(1, curve_steps + 1):
                points.append(_cubic_point(p0, p1, p2, p3, step / curve_steps))

    return _dedupe_points(points, eps=0.1)


def _point_on_path(
    path_d: str,
    at_start: bool,
    offset: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    points = _flatten_path(path_d)

    if len(points) < 2:
        point = points[0] if points else (0.0, 0.0)
        return point, (1.0, 0.0)

    walk_points = points if at_start else list(reversed(points))
    remaining = offset

    for idx in range(1, len(walk_points)):
        x1, y1 = walk_points[idx - 1]
        x2, y2 = walk_points[idx]
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5

        if length <= 0.1:
            continue

        if remaining <= length:
            ratio = remaining / length
            point = (x1 + dx * ratio, y1 + dy * ratio)
            tangent = (dx / length, dy / length)
            return point, tangent

        remaining -= length

    x1, y1 = walk_points[-2]
    x2, y2 = walk_points[-1]
    return walk_points[-1], _unit_vector((x1, y1), (x2, y2))


def _path_length(path_d: str) -> float:
    return _polyline_length(_flatten_path(path_d))


def _label_text_width(text: str) -> float:
    if not text:
        return 0.0

    if len(text) == 1:
        return 7.0

    return max(len(text) * 5.0, 7.0)


def _min_path_x_in_y_band(
    points: list[tuple[float, float]],
    top: float,
    bottom: float,
    fallback: float,
) -> float:
    values: list[float] = []

    for idx, (x, y) in enumerate(points):
        if top <= y <= bottom:
            values.append(x)

        if idx == 0:
            continue

        prev_x, prev_y = points[idx - 1]
        if max(prev_y, y) < top or min(prev_y, y) > bottom:
            continue

        if abs(y - prev_y) < 0.1:
            values.extend((prev_x, x))
            continue

        for boundary_y in (top, bottom):
            if min(prev_y, y) <= boundary_y <= max(prev_y, y):
                ratio = (boundary_y - prev_y) / (y - prev_y)
                values.append(prev_x + (x - prev_x) * ratio)

    return min(values) if values else fallback


def _multiplicity_label_pos_on_path(
    path_d: str,
    at_start: bool,
    text: str,
    along_offset: float = MULTIPLICITY_ENDPOINT_OFFSET,
) -> tuple[float, float]:
    path_points = _flatten_path(path_d)
    local_along_offset = min(
        along_offset,
        max(10.0, _polyline_length(path_points) * 0.35),
    )
    point, tangent = _point_on_path(path_d, at_start, local_along_offset)
    tx, ty = tangent
    text_w = _label_text_width(text)
    endpoint = path_points[0 if at_start else -1]

    if abs(tx) > abs(ty) * 4.0:
        if tx >= 0:
            x = endpoint[0] + MULTIPLICITY_HORIZONTAL_GAP
        else:
            x = endpoint[0] - text_w - MULTIPLICITY_HORIZONTAL_GAP

        return x, endpoint[1] + MULTIPLICITY_HORIZONTAL_BASELINE

    baseline_y = point[1] + MULTIPLICITY_BASELINE_SHIFT
    edge_x = _min_path_x_in_y_band(
        path_points,
        baseline_y - EDGE_LABEL_FONT_SIZE,
        baseline_y + 2.0,
        min(point[0], endpoint[0]),
    )

    return (
        edge_x - text_w - MULTIPLICITY_LINE_GAP,
        baseline_y,
    )

def _unit_vector(
    point: tuple[float, float],
    other: tuple[float, float],
) -> tuple[float, float]:
    dx = other[0] - point[0]
    dy = other[1] - point[1]

    length = max((dx * dx + dy * dy) ** 0.5, 1.0)
    return dx / length, dy / length


def _multiplicity_side(
    point: tuple[float, float],
    other: tuple[float, float],
) -> tuple[float, float]:
    dx = other[0] - point[0]
    dy = other[1] - point[1]

    if abs(dx) >= abs(dy):
        return 0.0, -1.0

    return -1.0, 0.0


def _polyline_length(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0

    length = 0.0
    for idx in range(1, len(points)):
        dx = points[idx][0] - points[idx - 1][0]
        dy = points[idx][1] - points[idx - 1][1]
        length += (dx * dx + dy * dy) ** 0.5

    return length


def _multiplicity_side_segment(
    points: list[tuple[float, float]],
    at_start: bool,
    fallback_point: tuple[float, float],
    fallback_other: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if len(points) < 3:
        return fallback_point, fallback_other

    if at_start:
        return points[1], points[2]

    return points[-2], points[-3]


def _multiplicity_label_pos(
    points: list[tuple[float, float]],
    at_start: bool,
    text: str,
    along_offset: float = 28.0,
    side_offset: float = 30.0,
) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0

    if len(points) == 1:
        point = points[0]
        other = (point[0] + 1.0, point[1])
    elif at_start:
        point = points[0]
        other = points[1]
    else:
        point = points[-1]
        other = points[-2]

    ux, uy = _unit_vector(point, other)
    side_point, side_other = _multiplicity_side_segment(
        points,
        at_start,
        point,
        other,
    )
    sx, sy = _multiplicity_side(side_point, side_other)
    side_dx = side_other[0] - side_point[0]
    side_dy = side_other[1] - side_point[1]
    text_w = max(len(text) * 7.0, 8.0)
    local_along_offset = min(
        along_offset,
        max(10.0, _polyline_length(points) * 0.18),
    )

    base_x = point[0] + ux * local_along_offset
    base_y = point[1] + uy * local_along_offset
    anchor_x = side_point[0] if abs(side_dx) < abs(side_dy) else base_x
    anchor_y = side_point[1] if abs(side_dy) < abs(side_dx) else base_y

    if sx < 0:
        return anchor_x - side_offset - text_w / 2, base_y + 4

    if sx > 0:
        return anchor_x + side_offset - text_w / 2, base_y + 4

    if sy < 0:
        return base_x - text_w / 2, anchor_y - side_offset

    return base_x - text_w / 2, anchor_y + side_offset + 12


def _edge_label_pos(points: list[tuple[float, float]]) -> tuple[float, float]:
    mid_idx = len(points) // 2
    if len(points) >= 2:
        x = (points[mid_idx - 1][0] + points[mid_idx][0]) / 2
        y = (points[mid_idx - 1][1] + points[mid_idx][1]) / 2
    else:
        x, y = points[0]

    if len(points) >= 2:
        prev_x, prev_y = points[mid_idx - 1]
        next_x, next_y = points[mid_idx]
        dx = next_x - prev_x
        dy = next_y - prev_y
        if abs(dx) < abs(dy):
            return x + 10, y - 4

    return x + 6, y - 6


def _primitive_kind(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _render_qualifier_metadata(end, end_index: int) -> str:
    parts: list[str] = []

    for idx, qualifier in enumerate(getattr(end, "qualifiers", []) or []):
        value = qualifier.initial_value
        parts.append(
            '<metadata '
            'data-type="association-end-qualifier" '
            f'data-end="{end_index}" '
            f'data-index="{idx}" '
            f'data-name="{_esc(qualifier.name)}" '
            f'data-visibility="{_esc(qualifier.visibility.value if qualifier.visibility else "")}" '
            f'data-scope="{_esc(qualifier.scope.value)}" '
            f'data-value-type="{_esc(qualifier.type_ or "")}" '
            f'data-multiplicity="{_esc(str(qualifier.multiplicity) if qualifier.multiplicity else "")}" '
            f'data-has-initial-value="{str(value is not None).lower()}" '
            f'data-initial-value-kind="{_esc(_primitive_kind(value))}" '
            f'data-initial-value="{_esc("" if value is None else value)}" '
            f'data-changeability="{_esc(qualifier.changeability.value if qualifier.changeability else "")}" '
            f'data-redefines="{_esc(qualifier.redefines or "")}"'
            '/>'
        )

    return "\n  ".join(parts)


def _edge_shape_svg(
    points: list[tuple[float, float]],
    path_d: str | None,
    attrs: str,
    extra_class: str = "",
) -> str:
    class_attr = "uml-edge-line"
    if extra_class:
        class_attr += f" {extra_class}"

    if path_d:
        return f'<path class="{class_attr}" d="{_path_attr(path_d)}"{attrs}/>'

    return f'<polyline class="{class_attr}" points="{_points_attr(points)}"{attrs}/>'


def _path_label_pos(path_d: str) -> tuple[float, float]:
    point, tangent = _point_on_path(path_d, True, _polyline_length(_flatten_path(path_d)) / 2)
    tx, ty = tangent

    if abs(tx) < abs(ty):
        return point[0] + 10, point[1] - 4

    return point[0] + 6, point[1] - 6


def render_association_svg(
    assoc,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
    data_type: str = "association",
    extra_data_attrs: str = "",
    extra_content: str = "",
) -> str:
    if not assoc.is_binary():
        return ""

    e1, e2 = assoc.ends

    end1_name = e1.participant_name
    end2_name = e2.participant_name

    p1 = positions.get(end1_name)
    p2 = positions.get(end2_name)

    if p1 is None or p2 is None:
        return ""

    points = _edge_route(p1, p2, route)

    marker_start = ""
    marker_end = ""
    if e1.aggregation == AggregationKind.COMPOSITION:
        marker_start = ' marker-start="url(#diamond-filled)"'
    elif e1.aggregation == AggregationKind.AGGREGATION:
        marker_start = ' marker-start="url(#diamond-empty)"'
    elif e2.aggregation == AggregationKind.COMPOSITION:
        marker_end = ' marker-end="url(#diamond-filled-end)"'
    elif e2.aggregation == AggregationKind.AGGREGATION:
        marker_end = ' marker-end="url(#diamond-empty-end)"'

    mult1 = str(e1.multiplicity) if e1.multiplicity else ""
    mult2 = str(e2.multiplicity) if e2.multiplicity else ""

    show_src_mult = e1.aggregation == AggregationKind.NONE
    show_tgt_mult = e2.aggregation == AggregationKind.NONE

    if path_d:
        src_mult_x, src_mult_y = _multiplicity_label_pos_on_path(path_d, True, mult1)
    else:
        src_mult_x, src_mult_y = _multiplicity_label_pos(points, True, mult1)

    if path_d:
        tgt_mult_x, tgt_mult_y = _multiplicity_label_pos_on_path(path_d, False, mult2)
    else:
        tgt_mult_x, tgt_mult_y = _multiplicity_label_pos(points, False, mult2)

    edge_shape = _edge_shape_svg(
        points,
        path_d,
        f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}"{marker_start}{marker_end}',
    )

    edge_class = "uml-edge"
    if data_type != "association":
        edge_class += f" uml-{data_type}"

    return f"""
<g class="{edge_class}"
   data-type="{_esc(data_type)}"
   data-name="{_esc(assoc.name or '')}"
   data-derived="{str(assoc.is_derived).lower()}"
   {extra_data_attrs}
   data-end1-class="{_esc(end1_name)}"
   data-end1-multiplicity="{_esc(mult1)}"
   data-end1-role="{_esc(e1.role or '')}"
   data-end1-navigable="{str(e1.navigable).lower() if e1.navigable is not None else ''}"
   data-end1-aggregation="{_esc(e1.aggregation.value)}"
   data-end1-role-visibility="{_esc(e1.role_visibility.value if e1.role_visibility else '')}"
   data-end1-collection-kind="{_esc(e1.collection_kind.value)}"
   data-end1-changeability="{_esc(e1.changeability.value if e1.changeability else '')}"
   data-end1-derived="{str(e1.is_derived).lower()}"
   data-end1-union="{str(e1.is_union).lower()}"
   data-end1-redefines="{_esc(e1.redefines or '')}"
   data-end1-role-type="{_esc(e1.role_type.name if e1.role_type else '')}"
   data-end1-subsets-role="{_esc(e1.subsets.role if e1.subsets and e1.subsets.role else '')}"
   data-end1-subsets-participant="{_esc(e1.subsets.participant_name if e1.subsets else '')}"
   data-end2-class="{_esc(end2_name)}"
   data-end2-multiplicity="{_esc(mult2)}"
   data-end2-role="{_esc(e2.role or '')}"
   data-end2-navigable="{str(e2.navigable).lower() if e2.navigable is not None else ''}"
   data-end2-aggregation="{_esc(e2.aggregation.value)}"
   data-end2-role-visibility="{_esc(e2.role_visibility.value if e2.role_visibility else '')}"
   data-end2-collection-kind="{_esc(e2.collection_kind.value)}"
   data-end2-changeability="{_esc(e2.changeability.value if e2.changeability else '')}"
   data-end2-derived="{str(e2.is_derived).lower()}"
   data-end2-union="{str(e2.is_union).lower()}"
   data-end2-redefines="{_esc(e2.redefines or '')}"
   data-end2-role-type="{_esc(e2.role_type.name if e2.role_type else '')}"
   data-end2-subsets-role="{_esc(e2.subsets.role if e2.subsets and e2.subsets.role else '')}"
   data-end2-subsets-participant="{_esc(e2.subsets.participant_name if e2.subsets else '')}">
  {edge_shape}
  {_render_qualifier_metadata(e1, 1)}
  {_render_qualifier_metadata(e2, 2)}
  {_render_label(mult1 if show_src_mult else "", src_mult_x, src_mult_y, "uml-multiplicity")}
  {_render_label(mult2 if show_tgt_mult else "", tgt_mult_x, tgt_mult_y, "uml-multiplicity")}
  {extra_content}
</g>
"""


def _midpoint_on_edge(
    points: list[tuple[float, float]],
    path_d: str | None = None,
) -> tuple[float, float]:
    if path_d:
        flattened = _flatten_path(path_d)
        point, _ = _point_on_path(path_d, True, _polyline_length(flattened) / 2)
        return point

    if not points:
        return 0.0, 0.0

    total = _polyline_length(points)
    if total <= 0:
        return points[len(points) // 2]

    target = total / 2
    walked = 0.0
    for start, end in zip(points, points[1:]):
        segment = math.hypot(end[0] - start[0], end[1] - start[1])
        if walked + segment >= target:
            ratio = (target - walked) / segment if segment else 0.0
            return (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        walked += segment

    return points[-1]


def _nearest_point_on_polyline(
    points: list[tuple[float, float]],
    target: tuple[float, float],
) -> tuple[float, float]:
    if not points:
        return target

    if len(points) == 1:
        return points[0]

    best_point = points[0]
    best_distance = float("inf")
    tx, ty = target

    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 0:
            candidate = start
        else:
            ratio = ((tx - x1) * dx + (ty - y1) * dy) / length_sq
            ratio = max(0.0, min(1.0, ratio))
            candidate = (x1 + dx * ratio, y1 + dy * ratio)

        distance = (candidate[0] - tx) ** 2 + (candidate[1] - ty) ** 2
        if distance < best_distance:
            best_distance = distance
            best_point = candidate

    return best_point


def _association_class_attach_point(
    points: list[tuple[float, float]],
    path_d: str | None,
    target: tuple[float, float],
) -> tuple[float, float]:
    if path_d:
        return _nearest_point_on_polyline(_flatten_path(path_d), target)

    return _nearest_point_on_polyline(points, target)


def _point_inside_rect(
    point: tuple[float, float],
    rect: ClassPosition,
    margin: float = 3.0,
) -> bool:
    x, y = point
    return (
        rect.x - margin <= x <= rect.x + rect.width + margin
        and rect.y - margin <= y <= rect.y + rect.height + margin
    )


def _segment_intersects_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: ClassPosition,
    margin: float = 3.0,
) -> bool:
    if _point_inside_rect(start, rect, margin) or _point_inside_rect(end, rect, margin):
        return True

    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    left = rect.x - margin
    right = rect.x + rect.width + margin
    top = rect.y - margin
    bottom = rect.y + rect.height + margin
    t0 = 0.0
    t1 = 1.0

    for p, q in (
        (-dx, x0 - left),
        (dx, right - x0),
        (-dy, y0 - top),
        (dy, bottom - y0),
    ):
        if p == 0:
            if q < 0:
                return False
            continue

        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)

    return t0 <= t1


def _association_class_anchor_candidates(
    class_pos: ClassPosition,
    target: tuple[float, float],
) -> list[tuple[float, float]]:
    cx, cy = _center(class_pos)
    x0 = class_pos.x
    x1 = class_pos.x + class_pos.width
    y0 = class_pos.y
    y1 = class_pos.y + class_pos.height

    candidates = []
    if target[1] >= cy:
        candidates.extend([(cx, y1), (x1, y1), (x0, y1)])
    else:
        candidates.extend([(cx, y0), (x1, y0), (x0, y0)])

    if target[0] >= cx:
        candidates.extend([(x1, cy), (x1, y1), (x1, y0)])
    else:
        candidates.extend([(x0, cy), (x0, y1), (x0, y0)])

    candidates.extend([
        (cx, y1),
        (cx, y0),
        (x1, cy),
        (x0, cy),
        _box_boundary_towards(class_pos, target),
    ])

    result: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for candidate in candidates:
        rounded = (round(candidate[0], 3), round(candidate[1], 3))
        if rounded in seen:
            continue
        seen.add(rounded)
        result.append(candidate)

    return result


def _association_class_anchor(
    class_pos: ClassPosition,
    target: tuple[float, float],
    obstacles: list[ClassPosition],
) -> tuple[float, float]:
    for candidate in _association_class_anchor_candidates(class_pos, target):
        if not any(_segment_intersects_rect(candidate, target, obstacle) for obstacle in obstacles):
            return candidate

    return _box_boundary_towards(class_pos, target)


def _polyline_length_value(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in zip(points, points[1:])
    )


def _clean_polyline_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    return _dedupe_points(points, eps=0.1)


def _polyline_hits_obstacles(
    points: list[tuple[float, float]],
    obstacles: list[ClassPosition],
) -> bool:
    return any(
        _segment_intersects_rect(start, end, obstacle)
        for start, end in zip(points, points[1:])
        for obstacle in obstacles
    )


def _association_class_connector_points(
    class_pos: ClassPosition,
    target: tuple[float, float],
    obstacles: list[ClassPosition],
) -> list[tuple[float, float]]:
    routes: list[list[tuple[float, float]]] = []
    for anchor in _association_class_anchor_candidates(class_pos, target):
        routes.extend([
            _clean_polyline_points([anchor, target]),
            _clean_polyline_points([anchor, (anchor[0], target[1]), target]),
            _clean_polyline_points([anchor, (target[0], anchor[1]), target]),
        ])

    valid_routes = [
        route
        for route in routes
        if len(route) >= 2 and not _polyline_hits_obstacles(route, obstacles)
    ]
    if valid_routes:
        return min(valid_routes, key=_polyline_length_value)

    return routes[0]


def _rounded_connector_path(points: list[tuple[float, float]], radius: float = 18.0) -> str:
    if len(points) < 2:
        return ""

    def fmt(point: tuple[float, float]) -> str:
        return f"{point[0]:.1f},{point[1]:.1f}"

    if len(points) == 2:
        start, end = points
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if abs(dx) > abs(dy):
            c1 = (start[0] + dx * 0.45, start[1])
            c2 = (end[0] - dx * 0.45, end[1])
        else:
            c1 = (start[0], start[1] + dy * 0.45)
            c2 = (end[0], end[1] - dy * 0.45)
        return f"M{fmt(start)} C{fmt(c1)} {fmt(c2)} {fmt(end)}"

    start, bend, end = points[0], points[1], points[-1]
    v1 = (bend[0] - start[0], bend[1] - start[1])
    v2 = (end[0] - bend[0], end[1] - bend[1])
    len1 = math.hypot(v1[0], v1[1])
    len2 = math.hypot(v2[0], v2[1])
    if len1 <= 0 or len2 <= 0:
        return _rounded_connector_path([start, end], radius=radius)

    r = min(radius, len1 / 2, len2 / 2)
    before = (bend[0] - v1[0] / len1 * r, bend[1] - v1[1] / len1 * r)
    after = (bend[0] + v2[0] / len2 * r, bend[1] + v2[1] / len2 * r)

    return f"M{fmt(start)} L{fmt(before)} Q{fmt(bend)} {fmt(after)} L{fmt(end)}"


def render_association_class_svg(
    assoc_class,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
    anchor_name: str | None = None,
    connector_route: list[tuple[float, float]] | None = None,
    connector_path_d: str | None = None,
) -> str:
    if not assoc_class.is_binary():
        return ""

    e1, e2 = assoc_class.ends
    p1 = positions.get(e1.participant_name)
    p2 = positions.get(e2.participant_name)
    class_pos = positions.get(assoc_class.associated_classifier.name)

    if p1 is None or p2 is None or class_pos is None:
        return ""

    associated_name = assoc_class.associated_classifier.name
    anchor_pos = positions.get(anchor_name) if anchor_name else None
    if anchor_pos is not None:
        anchor_center = _center(anchor_pos)
        points = _edge_route(p1, p2, route)
        attach_point = _association_class_attach_point(
            points,
            path_d,
            anchor_center,
        )
        connector_points = _points_with_endpoint(
            _edge_route(class_pos, anchor_pos, connector_route),
            attach_point,
            at_start=False,
        )
        connector_path_d = _path_with_endpoint(
            connector_path_d,
            attach_point,
            at_start=False,
        )
        connector = _edge_shape_svg(
            connector_points,
            connector_path_d,
            (
                f' fill="none" stroke="{EDGE_COLOR}" '
                f'stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
                f'stroke-dasharray="{EDGE_DASH_ARRAY}"'
            ),
            extra_class="uml-association-class-link",
        )
        anchor_dot = (
            f'<circle class="uml-association-class-anchor" '
            f'cx="{attach_point[0]:.1f}" cy="{attach_point[1]:.1f}" r="3.2" '
            f'fill="{EDGE_COLOR}" stroke="{EDGE_COLOR}" stroke-width="1.0"/>'
        )

        return render_association_svg(
            assoc_class,
            positions,
            route,
            path_d,
            data_type="association-class",
            extra_data_attrs=f'data-associated-classifier="{_esc(associated_name)}"',
            extra_content=f"{connector}\n  {anchor_dot}",
        )

    points = _edge_route(p1, p2, route)
    mid_x, mid_y = _midpoint_on_edge(points, path_d)
    connector_points = _association_class_connector_points(
        class_pos,
        (mid_x, mid_y),
        [p1, p2],
    )
    connector_path = _rounded_connector_path(connector_points)
    connector = (
        f'<path class="uml-edge-line uml-association-class-link" '
        f'd="{_path_attr(connector_path)}" '
        f'fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
        f'stroke-dasharray="{EDGE_DASH_ARRAY}"/>'
    )

    return render_association_svg(
        assoc_class,
        positions,
        route,
        path_d,
        data_type="association-class",
        extra_data_attrs=f'data-associated-classifier="{_esc(associated_name)}"',
        extra_content=connector,
    )


def _render_label(
    text: str,
    x: float,
    y: float,
    cls: str = "",
    background: bool = False,
) -> str:
    if not text:
        return ""
    class_attr = f' class="{cls}"' if cls else ""
    label = (
        f'<text{class_attr} x="{x:.1f}" y="{y:.1f}" '
        f'font-family="{EDGE_LABEL_FONT}" font-size="{EDGE_LABEL_FONT_SIZE}" '
        f'fill="black">{_esc(text)}</text>'
    )
    if not background:
        return label

    width = max(_label_text_width(text) + 4, 10)
    return (
        f'<g{class_attr}>'
        f'<rect x="{x - 2:.1f}" y="{y - 12:.1f}" width="{width:.1f}" height="15" '
        f'fill="white" opacity="0.85" stroke="none"/>'
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{EDGE_LABEL_FONT}" '
        f'font-size="{EDGE_LABEL_FONT_SIZE}" fill="black">{_esc(text)}</text>'
        f'</g>'
    )

def render_generalization_svg(
    gen,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
) -> str:
    src = gen.specific.name
    tgt = gen.general.name

    p1 = positions.get(src)
    p2 = positions.get(tgt)

    if p1 is None or p2 is None:
        return ""

    points = _edge_route(p1, p2, route)

    edge_shape = _edge_shape_svg(
        points,
        path_d,
        f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" marker-end="url(#triangle-empty)"',
    )

    return f"""
<g class="uml-edge"
   data-type="generalization"
   data-src="{_esc(src)}"
   data-tgt="{_esc(tgt)}"
   data-substitutable="{str(gen.is_substitutable).lower()}">
  {edge_shape}
</g>
"""

def render_dependency_svg(
    dep,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
) -> str:
    src = dep.client.name
    tgt = dep.supplier.name

    p1 = positions.get(src)
    p2 = positions.get(tgt)

    if p1 is None or p2 is None:
        return ""

    points = _edge_route(p1, p2, route)

    stereo = dep.stereotype.value if dep.stereotype else ""
    label = f"«{stereo}»" if stereo else ""

    if path_d:
        mid_x, mid_y = _path_label_pos(path_d)
    else:
        mid_idx = len(points) // 2
        mid_x = (points[mid_idx - 1][0] + points[mid_idx][0]) / 2
        mid_y = (points[mid_idx - 1][1] + points[mid_idx][1]) / 2

    edge_shape = _edge_shape_svg(
        points,
        path_d,
        (
            f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
            f'stroke-dasharray="{EDGE_DASH_ARRAY}" marker-end="url(#arrow-filled)"'
        ),
    )

    return f"""
<g class="uml-edge"
   data-type="dependency"
   data-src="{_esc(src)}"
   data-tgt="{_esc(tgt)}"
   data-stereotype="{_esc(stereo)}">
  {edge_shape}
  {_render_label(label, mid_x + 6, mid_y - 6, "uml-edge-label")}
</g>
"""


def render_template_binding_svg(
    binding,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
    substitution_routes: list[tuple[str, str, list[tuple[float, float]] | None, str | None]] | None = None,
) -> str:
    src = binding.bound_element.name
    tgt = binding.template.name

    p1 = positions.get(src)
    p2 = positions.get(tgt)
    if p1 is None or p2 is None:
        return ""

    points = _edge_route(p1, p2, route)
    if path_d:
        mid_x, mid_y = _path_label_pos(path_d)
    else:
        mid_idx = len(points) // 2
        mid_x = (points[mid_idx - 1][0] + points[mid_idx][0]) / 2
        mid_y = (points[mid_idx - 1][1] + points[mid_idx][1]) / 2

    edge_shape = _edge_shape_svg(
        points,
        path_d,
        (
            f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
            f'stroke-dasharray="{EDGE_DASH_ARRAY}" marker-end="url(#arrow-filled)"'
        ),
    )

    substitution_metadata = []
    for index, (formal, actual) in enumerate(binding.substitutions.items()):
        substitution_metadata.append(
            '<metadata '
            'data-type="template-substitution" '
            f'data-index="{index}" '
            f'data-formal="{_esc(formal)}" '
            f'data-actual="{_esc(actual)}"/>'
        )

    substitution_edges: list[str] = []
    for formal, actual, actual_route, actual_path_d in substitution_routes or []:
        actual_pos = positions.get(actual)
        if actual_pos is None:
            continue

        actual_points = _edge_route(p1, actual_pos, actual_route)
        if actual_path_d:
            label_x, label_y = _path_label_pos(actual_path_d)
        else:
            mid_idx = len(actual_points) // 2
            label_x = (actual_points[mid_idx - 1][0] + actual_points[mid_idx][0]) / 2
            label_y = (actual_points[mid_idx - 1][1] + actual_points[mid_idx][1]) / 2

        substitution_edges.append(
            f"""
  <g class="uml-edge uml-template-substitution"
     data-type="template-binding-substitution"
     data-bound-element="{_esc(src)}"
     data-template="{_esc(tgt)}"
     data-formal="{_esc(formal)}"
     data-actual="{_esc(actual)}">
    {_edge_shape_svg(
        actual_points,
        actual_path_d,
        (
            f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
            f'stroke-dasharray="{EDGE_DASH_ARRAY}" marker-end="url(#arrow-filled)"'
        ),
    )}
    {_render_label(f"{formal} = {actual}", label_x + 6, label_y - 6, "uml-edge-label", background=True)}
  </g>
"""
        )

    return f"""
<g class="uml-edge uml-template-binding"
   data-type="template-binding"
   data-bound-element="{_esc(src)}"
   data-template="{_esc(tgt)}"
   data-substitutions-count="{len(binding.substitutions)}">
  {edge_shape}
  {"".join(substitution_metadata)}
  {_render_label("«bind»", mid_x + 6, mid_y - 6, "uml-edge-label", background=True)}
</g>
{''.join(substitution_edges)}
"""


def render_realization_svg(
    real,
    positions: dict[str, ClassPosition],
    route: list[tuple[float, float]] | None = None,
    path_d: str | None = None,
) -> str:
    src = real.implementer.name
    tgt = real.interface_.name

    p1 = positions.get(src)
    p2 = positions.get(tgt)

    if p1 is None or p2 is None:
        return ""

    points = _edge_route(p1, p2, route)

    edge_shape = _edge_shape_svg(
        points,
        path_d,
        (
            f' fill="none" stroke="{EDGE_COLOR}" stroke-width="{EDGE_STROKE_WIDTH:.1f}" '
            f'stroke-dasharray="{EDGE_DASH_ARRAY}" marker-end="url(#triangle-empty)"'
        ),
    )

    return f"""
<g class="uml-edge"
   data-type="realization"
   data-src="{_esc(src)}"
   data-tgt="{_esc(tgt)}">
  {edge_shape}
</g>
"""

def _node_label(cls) -> str:
    """Build Graphviz record label for UML class."""
    title = cls.name
    if getattr(cls, "is_abstract", False):
        title = f"<I>{html.escape(title)}</I>"
    else:
        title = html.escape(title)

    if getattr(cls, "stereotype", None):
        st = html.escape(cls.stereotype.value)
        title = f"&laquo;{st}&raquo;<BR/>{title}"

    attrs = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(a.to_text()) for a in getattr(cls, "attributes", [])
    ) or " "
    ops = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(o.to_text()) for o in getattr(cls, "operations", [])
    ) or " "
    return f"<{title}<BR/>{attrs}<BR/>{ops}>"


def _association_class_anchor_name(index: int) -> str:
    return f"__ontol_v3_association_class_anchor_{index}"


def diagram_to_layout_dot(diagram: ClassDiagram):
    node_map = {}
    name_to_node = {}
    association_class_anchor_names: list[str | None] = [
        None for _ in diagram.association_classes
    ]

    lines = [
        "digraph UML {",
        "  graph [rankdir=TB, splines=true, nodesep=0.8, ranksep=0.9, pad=0.3];",
        "  node [shape=box, fixedsize=true, label=\"\", style=invis];",
        "  edge [style=invis];",
    ]

    for idx, (name, cls) in enumerate(diagram.classifiers.items()):
        node_id = f"C{idx}"
        node_map[node_id] = name
        name_to_node[name] = node_id

        width_px, height_px = cls.get_box_size()

        lines.append(
            f'  {node_id} [width="{width_px / PX_PER_INCH:.3f}", '
            f'height="{height_px / PX_PER_INCH:.3f}"];'
        )

    for assoc in diagram.associations:
        if not assoc.is_binary():
            continue

        src = assoc.ends[0].participant_name
        tgt = assoc.ends[1].participant_name

        if src in name_to_node and tgt in name_to_node:
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]};")

    for idx, assoc_class in enumerate(diagram.association_classes):
        if not assoc_class.is_binary():
            continue

        associated = assoc_class.associated_classifier.name
        src = assoc_class.ends[0].participant_name
        tgt = assoc_class.ends[1].participant_name

        if (
            associated not in name_to_node
            or src not in name_to_node
            or tgt not in name_to_node
        ):
            continue

        anchor_id = f"AC{idx}"
        anchor_name = _association_class_anchor_name(idx)
        node_map[anchor_id] = anchor_name
        name_to_node[anchor_name] = anchor_id
        association_class_anchor_names[idx] = anchor_name

        lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]} [weight=3];")
        lines.append(
            f'  {anchor_id} [shape=point, width="0.01", height="0.01", '
            'fixedsize=true, label="", style=invis];'
        )
        lines.append(f"  {name_to_node[src]} -> {anchor_id} [style=invis, weight=3];")
        lines.append(f"  {anchor_id} -> {name_to_node[tgt]} [style=invis, weight=3];")
        lines.append(f"  {name_to_node[associated]} -> {anchor_id} [weight=1];")

    for gen in diagram.generalizations:
        src = gen.specific.name
        tgt = gen.general.name

        if src in name_to_node and tgt in name_to_node:
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]};")

    for dep in diagram.dependencies:
        src = dep.client.name
        tgt = dep.supplier.name

        if src in name_to_node and tgt in name_to_node:
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]};")

    for binding in diagram.template_bindings:
        src = binding.bound_element.name
        tgt = binding.template.name

        if src in name_to_node and tgt in name_to_node:
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]};")

        for actual in binding.substitutions.values():
            if src in name_to_node and actual in name_to_node:
                lines.append(f"  {name_to_node[src]} -> {name_to_node[actual]};")

    for real in diagram.realizations:
        src = real.implementer.name
        tgt = real.interface_.name

        if src in name_to_node and tgt in name_to_node:
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]};")

    lines.append("}")
    return "\n".join(lines), node_map, association_class_anchor_names


def _run_dot_to_plain(dot_text: str) -> str:
    try:
        result = subprocess.run(
            [_dot_command(), "-Tplain"],
            input=dot_text.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Graphviz 'dot' не найден. Установите Graphviz и добавьте dot в PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Ошибка Graphviz dot: {stderr}") from exc

    return result.stdout.decode("utf-8", errors="replace")


def _run_dot_to_svg(dot_text: str) -> str:
    try:
        result = subprocess.run(
            [_dot_command(), "-Tsvg"],
            input=dot_text.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Graphviz 'dot' РЅРµ РЅР°Р№РґРµРЅ. РЈСЃС‚Р°РЅРѕРІРёС‚Рµ Graphviz Рё РґРѕР±Р°РІСЊС‚Рµ dot РІ PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"РћС€РёР±РєР° Graphviz dot: {stderr}") from exc

    return result.stdout.decode("utf-8", errors="replace")


def _make_edges_visible(dot_text: str) -> str:
    return dot_text.replace(
        "  edge [style=invis];",
        f'  edge [color="{EDGE_COLOR}", penwidth={EDGE_STROKE_WIDTH:.1f}, arrowhead=none];',
    )


def _extract_graphviz_svg_paths(svg_text: str) -> tuple[
    list[tuple[str, str, str]],
    str,
    float,
    float,
]:
    root = ET.fromstring(svg_text)
    ns = "{http://www.w3.org/2000/svg}"
    graph = next(
        (
            group
            for group in root.findall(f"{ns}g")
            if group.get("class") == "graph"
        ),
        None,
    )

    if graph is None:
        return [], "", 0.0, 0.0

    transform = graph.get("transform", "")
    view_box = [float(value) for value in root.get("viewBox", "0 0 0 0").split()]
    paths: list[tuple[str, str, str]] = []

    for edge in graph.findall(f"{ns}g"):
        if edge.get("class") != "edge":
            continue

        path = edge.find(f"{ns}path")
        title = edge.find(f"{ns}title")
        if path is None or not path.get("d") or title is None or not title.text:
            continue

        if "->" not in title.text:
            continue

        src_id, tgt_id = [part.strip() for part in title.text.split("->", 1)]
        paths.append((src_id, tgt_id, path.get("d", "")))

    return paths, transform, view_box[2], view_box[3]


def _shift_layout_to_svg_viewbox(
    plain_text: str,
    diagram: ClassDiagram,
    node_map: dict[str, str],
    transform: str,
) -> tuple[
    dict[str, ClassPosition],
    list[tuple[str, str, list[tuple[float, float]]]],
]:
    positions, routes = parse_plain_layout(plain_text, diagram, node_map)
    graph_height = next(
        (
            float(line.split()[3]) * PX_PER_INCH
            for line in plain_text.splitlines()
            if line.startswith("graph ")
        ),
        0.0,
    )

    match = re.search(r"translate\(([-\d.]+)\s+([-\d.]+)\)", transform)
    tx, ty = (float(match.group(1)), float(match.group(2))) if match else (0.0, graph_height)
    dx = tx - MARGIN
    dy = ty - (MARGIN + graph_height)

    shifted_positions = {
        name: ClassPosition(
            classifier_name=name,
            x=pos.x + dx,
            y=pos.y + dy,
            width=pos.width,
            height=pos.height,
        )
        for name, pos in positions.items()
    }
    shifted_routes = [
        (src, tgt, [(x + dx, y + dy) for x, y in points])
        for src, tgt, points in routes
    ]

    return shifted_positions, shifted_routes


def _replace_polyline_with_path(svg: str, path_d: str, transform: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = re.sub(r'\s+points="[^"]*"', "", match.group(1))
        transform_attr = f' transform="{_transform_attr(transform)}"' if transform else ""
        return f'<path d="{_path_attr(path_d)}"{transform_attr}{attrs}/>'

    return re.sub(r"<polyline([^>]*)/>", replace, svg, count=1, flags=re.S)

def parse_plain_layout(
    plain_text: str,
    diagram: ClassDiagram,
    node_map: dict[str, str],
):
    positions: dict[str, ClassPosition] = {}
    edge_routes: list[tuple[str, str, list[tuple[float, float]]]] = []

    graph_height_px = 0.0

    for line in plain_text.splitlines():
        parts = line.split()

        if not parts:
            continue

        if parts[0] == "graph":
            graph_height_px = float(parts[3]) * PX_PER_INCH

        elif parts[0] == "node":
            node_id = parts[1]
            class_name = node_map.get(node_id)
            if class_name is None:
                continue

            center_x_px = float(parts[2]) * PX_PER_INCH
            center_y_px = float(parts[3]) * PX_PER_INCH

            cls = diagram.classifiers.get(class_name)
            if cls is not None:
                width_px, height_px = cls.get_box_size()
            else:
                width_px = max(float(parts[4]) * PX_PER_INCH, 1.0)
                height_px = max(float(parts[5]) * PX_PER_INCH, 1.0)

            x = MARGIN + center_x_px - width_px / 2
            y = MARGIN + graph_height_px - center_y_px - height_px / 2

            positions[class_name] = ClassPosition(
                classifier_name=class_name,
                x=x,
                y=y,
                width=width_px,
                height=height_px,
            )

        elif parts[0] == "edge":
            src_name = node_map.get(parts[1])
            tgt_name = node_map.get(parts[2])

            if src_name is None or tgt_name is None:
                continue

            point_count = int(parts[3])
            raw_points = parts[4 : 4 + point_count * 2]

            points = []

            for i in range(0, len(raw_points), 2):
                x = MARGIN + float(raw_points[i]) * PX_PER_INCH
                y = MARGIN + graph_height_px - float(raw_points[i + 1]) * PX_PER_INCH
                points.append((x, y))

            edge_routes.append((src_name, tgt_name, points))

    return positions, edge_routes

def diagram_to_graphviz_svg(diagram: ClassDiagram, theme: str = DEFAULT_SVG_THEME) -> str:
    resolved_theme, svg_style = _load_svg_style(theme)
    edge_route_map: dict[tuple[str, str], list[list[tuple[float, float]]]] = {}
    graphviz_path_map: dict[tuple[str, str], list[str]] = {}

    if getattr(diagram, "manual_layout", False):
        positions = diagram.positions
        association_class_anchor_names: list[str | None] = [
            None for _ in diagram.association_classes
        ]
        width = max((p.x + p.width for p in positions.values()), default=0) + MARGIN
        height = max((p.y + p.height for p in positions.values()), default=0) + MARGIN
    else:
        dot_text, node_map, association_class_anchor_names = diagram_to_layout_dot(diagram)
        visible_dot_text = _make_edges_visible(dot_text)
        graphviz_svg = _run_dot_to_svg(visible_dot_text)
        graphviz_edges, graphviz_transform, graphviz_width, graphviz_height = (
            _extract_graphviz_svg_paths(graphviz_svg)
        )
        plain_text = _run_dot_to_plain(visible_dot_text)

        positions, edge_routes = _shift_layout_to_svg_viewbox(
            plain_text,
            diagram,
            node_map,
            graphviz_transform,
        )

        for src, tgt, points in edge_routes:
            edge_route_map.setdefault((src, tgt), []).append(points)

        for src_id, tgt_id, path_d in graphviz_edges:
            src = node_map.get(src_id)
            tgt = node_map.get(tgt_id)
            if src and tgt:
                graphviz_path_map.setdefault((src, tgt), []).append(
                    _transform_path_d(path_d, graphviz_transform)
                )

        diagram.positions = {
            name: pos
            for name, pos in positions.items()
            if name in diagram.classifiers
        }

        width = graphviz_width or max((p.x + p.width for p in positions.values()), default=0) + MARGIN
        height = graphviz_height or max((p.y + p.height for p in positions.values()), default=0) + MARGIN

    SVG_DEFS = """
    <defs>
      <linearGradient id="uml-yellow-title-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#f0c955"/>
        <stop offset="50%" stop-color="#ffebc2"/>
        <stop offset="100%" stop-color="#f0c955"/>
      </linearGradient>

      <linearGradient id="uml-yellow-section-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#f5d56b"/>
        <stop offset="50%" stop-color="#fff1cf"/>
        <stop offset="100%" stop-color="#f0c955"/>
      </linearGradient>

      <marker id="diamond-empty" markerWidth="12" markerHeight="8" viewBox="0 0 12 8" refX="0" refY="4" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-hollow" d="M 0 4 L 6 0 L 12 4 L 6 8 Z" fill="white" stroke="#181818" stroke-width="1"/>
      </marker>

      <marker id="diamond-filled" markerWidth="12" markerHeight="8" viewBox="0 0 12 8" refX="0" refY="4" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-filled" d="M 0 4 L 6 0 L 12 4 L 6 8 Z" fill="#181818" stroke="#181818" stroke-width="1"/>
      </marker>

      <marker id="diamond-empty-end" markerWidth="12" markerHeight="8" viewBox="0 0 12 8" refX="12" refY="4" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-hollow" d="M 0 4 L 6 0 L 12 4 L 6 8 Z" fill="white" stroke="#181818" stroke-width="1"/>
      </marker>

      <marker id="diamond-filled-end" markerWidth="12" markerHeight="8" viewBox="0 0 12 8" refX="12" refY="4" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-filled" d="M 0 4 L 6 0 L 12 4 L 6 8 Z" fill="#181818" stroke="#181818" stroke-width="1"/>
      </marker>

      <marker id="arrow-filled" markerWidth="9" markerHeight="8" viewBox="0 0 9 8" refX="9" refY="4" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-filled" d="M 9 4 L 0 0 L 4 4 L 0 8 Z" fill="#181818" stroke="#181818" stroke-width="1"/>
      </marker>

      <marker id="triangle-empty" markerWidth="18" markerHeight="12" viewBox="0 0 18 12" refX="18" refY="6" orient="auto" markerUnits="userSpaceOnUse">
        <path class="uml-marker uml-marker-hollow" d="M 18 6 L 0 0 L 0 12 Z" fill="white" stroke="#181818" stroke-width="1"/>
      </marker>
    </defs>
    """

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'class="uml-diagram" data-theme="{_esc(resolved_theme)}" data-title="{_esc(diagram.title)}">',
        SVG_DEFS,
        svg_style,
    ]
    edge_parts: list[str] = []

    for assoc in diagram.associations:
        if assoc.is_binary():
            src = assoc.ends[0].participant_name
            tgt = assoc.ends[1].participant_name
            routes = edge_route_map.get((src, tgt), [])
            route = routes.pop(0) if routes else None
            paths = graphviz_path_map.get((src, tgt), [])
            path_d = paths.pop(0) if paths else None
        else:
            route = None
            path_d = None

        edge_svg = render_association_svg(assoc, positions, route, path_d)
        edge_parts.append(edge_svg)

    for idx, assoc_class in enumerate(diagram.association_classes):
        anchor_name = (
            association_class_anchor_names[idx]
            if idx < len(association_class_anchor_names)
            else None
        )
        if assoc_class.is_binary():
            src = assoc_class.ends[0].participant_name
            tgt = assoc_class.ends[1].participant_name
            routes = edge_route_map.get((src, tgt), [])
            route = routes.pop(0) if routes else None
            paths = graphviz_path_map.get((src, tgt), [])
            path_d = paths.pop(0) if paths else None

            if anchor_name:
                associated = assoc_class.associated_classifier.name
                connector_routes = edge_route_map.get((associated, anchor_name), [])
                connector_route = connector_routes.pop(0) if connector_routes else None
                connector_paths = graphviz_path_map.get((associated, anchor_name), [])
                connector_path_d = connector_paths.pop(0) if connector_paths else None
            else:
                connector_route = None
                connector_path_d = None
        else:
            route = None
            path_d = None
            connector_route = None
            connector_path_d = None

        edge_svg = render_association_class_svg(
            assoc_class,
            positions,
            route,
            path_d,
            anchor_name=anchor_name,
            connector_route=connector_route,
            connector_path_d=connector_path_d,
        )
        edge_parts.append(edge_svg)

    for gen in diagram.generalizations:
        src = gen.specific.name
        tgt = gen.general.name
        routes = edge_route_map.get((src, tgt), [])
        route = routes.pop(0) if routes else None
        paths = graphviz_path_map.get((src, tgt), [])
        path_d = paths.pop(0) if paths else None

        edge_svg = render_generalization_svg(gen, positions, route, path_d)
        edge_parts.append(edge_svg)

    for dep in diagram.dependencies:
        src = dep.client.name
        tgt = dep.supplier.name
        routes = edge_route_map.get((src, tgt), [])
        route = routes.pop(0) if routes else None
        paths = graphviz_path_map.get((src, tgt), [])
        path_d = paths.pop(0) if paths else None

        edge_svg = render_dependency_svg(dep, positions, route, path_d)
        edge_parts.append(edge_svg)

    for binding in diagram.template_bindings:
        src = binding.bound_element.name
        tgt = binding.template.name
        routes = edge_route_map.get((src, tgt), [])
        route = routes.pop(0) if routes else None
        paths = graphviz_path_map.get((src, tgt), [])
        path_d = paths.pop(0) if paths else None

        substitution_routes = []
        for formal, actual in binding.substitutions.items():
            actual_routes = edge_route_map.get((src, actual), [])
            actual_route = actual_routes.pop(0) if actual_routes else None
            actual_paths = graphviz_path_map.get((src, actual), [])
            actual_path_d = actual_paths.pop(0) if actual_paths else None
            substitution_routes.append((formal, actual, actual_route, actual_path_d))

        edge_svg = render_template_binding_svg(
            binding,
            positions,
            route,
            path_d,
            substitution_routes=substitution_routes,
        )
        edge_parts.append(edge_svg)

    for real in diagram.realizations:
        src = real.implementer.name
        tgt = real.interface_.name
        routes = edge_route_map.get((src, tgt), [])
        route = routes.pop(0) if routes else None
        paths = graphviz_path_map.get((src, tgt), [])
        path_d = paths.pop(0) if paths else None

        edge_svg = render_realization_svg(real, positions, route, path_d)
        edge_parts.append(edge_svg)

    parts.extend(edge_parts)

    for name, cls in diagram.classifiers.items():
        pos = positions[name]
        parts.append(cls.to_svg(pos.x, pos.y, class_id=name))

    parts.append("</svg>")

    return "\n".join(parts)
