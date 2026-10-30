"""
Экспорт SVG в растровые форматы PNG и JPG.

Использует cairosvg для SVG→PNG и Pillow для PNG→JPG.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Union

try:
    import cairosvg
except ImportError:
    cairosvg = None

try:
    from PIL import Image
except ImportError:
    Image = None


def svg_to_png(
    svg_content: Union[str, bytes],
    output: Union[None, Path, str, io.BytesIO] = None,
    scale: float = 1.0,
    dpi: float = 96,
) -> bytes:
    """
    Конвертирует SVG в PNG.

    :param svg_content: SVG как строка или байты
    :param output: путь к файлу или BytesIO для записи; None — вернуть байты
    :param scale: масштаб (2.0 = двойное разрешение)
    :param dpi: точек на дюйм
    :return: PNG в виде байтов
    """
    if cairosvg is None:
        raise ImportError("Установите cairosvg: pip install cairosvg")

    data = svg_content.encode("utf-8") if isinstance(svg_content, str) else svg_content

    if output is not None:
        if isinstance(output, (Path, str)):
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            cairosvg.svg2png(
                bytestring=data,
                write_to=str(output),
                scale=scale,
                dpi=dpi,
            )
            return output.read_bytes()
        if isinstance(output, io.BytesIO):
            cairosvg.svg2png(
                bytestring=data,
                write_to=output,
                scale=scale,
                dpi=dpi,
            )
            return output.getvalue()

    buf = io.BytesIO()
    cairosvg.svg2png(
        bytestring=data,
        write_to=buf,
        scale=scale,
        dpi=dpi,
    )
    return buf.getvalue()


def svg_to_jpg(
    svg_content: Union[str, bytes],
    output: Union[None, Path, str, io.BytesIO] = None,
    scale: float = 1.0,
    dpi: float = 96,
    quality: int = 90,
) -> bytes:
    """
    Конвертирует SVG в JPG (через промежуточный PNG).

    :param svg_content: SVG как строка или байты
    :param output: путь к файлу или BytesIO; None — вернуть байты
    :param scale: масштаб
    :param dpi: точек на дюйм
    :param quality: качество JPG 1–100
    :return: JPG в виде байтов
    """
    if Image is None:
        raise ImportError("Установите Pillow: pip install Pillow")

    png_bytes = svg_to_png(svg_content, output=None, scale=scale, dpi=dpi)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    if output is not None:
        if isinstance(output, (Path, str)):
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(output), "JPEG", quality=quality)
            return output.read_bytes()
        if isinstance(output, io.BytesIO):
            img.save(output, "JPEG", quality=quality)
            return output.getvalue()

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def export_available() -> bool:
    """Проверяет, доступен ли экспорт в PNG/JPG (установлены cairosvg и Pillow)."""
    return cairosvg is not None and Image is not None
