"""Read measurements and text from a DXF drawing.

The plotted sheet is a separate file. This module does not render the DXF.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFEntity
    from ezdxf.layouts.layout import Layout

_MAX_LAYERS = 40
_MAX_TEXTS = 40
_MAX_TEXT_CHARS = 160
_MAX_BLOCKS = 40
_MAX_DIMENSIONS = 40
_MAX_ENTITIES = 20000

_UNIT_NAMES = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimeters",
    5: "centimeters",
    6: "meters",
    7: "kilometers",
    8: "microinches",
    9: "mils",
    10: "yards",
    11: "angstroms",
    12: "nanometers",
    13: "microns",
    14: "decimeters",
    15: "decameters",
    16: "hectometers",
    17: "gigameters",
    18: "astronomical units",
    19: "light years",
    20: "parsecs",
}

_DWG_SENTINEL = b"AC10"
_BINARY_DXF_SENTINEL = b"AutoCAD Binary DXF"


@dataclass(frozen=True)
class DxfLayer:
    name: str
    entity_count: int


@dataclass(frozen=True)
class DxfText:
    """A text entity. A number here is text, not a dimension measurement."""

    space: str
    layer: str
    kind: str
    value: str


@dataclass(frozen=True)
class DxfDimension:
    space: str
    layer: str
    measurement: float | None
    text_override: str | None


@dataclass(frozen=True)
class DxfDrawing:
    units: str
    layers: list[DxfLayer]
    texts: list[DxfText]
    dimensions: list[DxfDimension]
    blocks: list[str]
    text_count: int
    dimension_count: int
    block_count: int
    truncated: bool


def summarize_dxf(data: bytes) -> str:
    """Short text for indexing. The review tool reads the original bytes."""
    drawing = parse_dxf(data)
    layer_names = ", ".join(layer.name for layer in drawing.layers[:20]) or "none"
    samples = "; ".join(item.value for item in drawing.texts[:10])
    lines = [
        "DXF drawing.",
        f"Units: {drawing.units}",
        f"Layers: {layer_names}",
        f"Text entities: {drawing.text_count}",
        f"Dimension entities: {drawing.dimension_count}",
    ]
    if samples:
        lines.append(f"Text: {samples}")
    return "\n".join(lines)


def parse_dxf(data: bytes) -> DxfDrawing:
    """Parse units, layers, text, blocks, and DIMENSION entities."""
    if data.startswith(_DWG_SENTINEL):
        raise ValueError(
            "This file is a DWG drawing. Export a DXF file and upload that."
        )

    return _read_document(_load_document(data))


def format_measured_section(drawing: DxfDrawing, filename: str) -> str:
    """Format the DXF extract. Text stays labeled as text."""
    lines = [
        "## measured",
        f"Source: {filename}",
        f"Units: {drawing.units}",
        "Text lines are not dimension entities. A number in a text line is not a measurement.",
        "Layers:",
    ]
    if drawing.layers:
        lines.extend(
            f"- {layer.name}: {layer.entity_count} entities" for layer in drawing.layers
        )
    else:
        lines.append("- none")

    lines.append(f"Text ({drawing.text_count}):")
    if drawing.texts:
        lines.extend(
            f"- {item.space} / {item.layer} / {item.kind}: {item.value}"
            for item in drawing.texts
        )
    else:
        lines.append("- none")

    lines.append(f"Dimension entities ({drawing.dimension_count}):")
    if drawing.dimensions:
        for item in drawing.dimensions:
            measurement = (
                "unavailable" if item.measurement is None else str(item.measurement)
            )
            override = item.text_override or "none"
            lines.append(
                f"- {item.space} / {item.layer}: measurement={measurement} "
                f"text_override={override}"
            )
    else:
        lines.append("- none")

    lines.append(f"Blocks ({drawing.block_count}):")
    if drawing.blocks:
        lines.extend(f"- {name}" for name in drawing.blocks)
    else:
        lines.append("- none")

    if drawing.truncated:
        lines.append("The DXF listing is truncated.")
    return "\n".join(lines)


def _load_document(data: bytes) -> Drawing:
    import ezdxf
    from ezdxf import recover
    from ezdxf.document import Drawing as DxfDocument
    from ezdxf.lldxf.tagger import binary_tags_loader

    if data.startswith(_BINARY_DXF_SENTINEL):
        try:
            return DxfDocument.load(binary_tags_loader(data))
        except Exception as error:
            raise ValueError("DXF file could not be parsed.") from error

    text = TextIOWrapper(BytesIO(data), encoding="utf-8", errors="surrogateescape")
    try:
        return ezdxf.read(text)
    except Exception:
        try:
            document, _auditor = recover.read(BytesIO(data))
        except Exception as error:
            raise ValueError("DXF file could not be parsed.") from error
        return document
    finally:
        text.detach()


def _read_document(document: Drawing) -> DxfDrawing:
    units = _units(document)
    counts: dict[str, int] = {}
    table_names: list[str] = []
    for layer in document.layers:
        name = str(layer.dxf.name)
        table_names.append(name)
        counts.setdefault(name, 0)

    texts: list[DxfText] = []
    dimensions: list[DxfDimension] = []
    blocks: list[str] = []
    seen_blocks: set[str] = set()
    text_count = 0
    dimension_count = 0
    scanned = 0
    truncated = False

    for space, layout in _layouts(document):
        for entity in layout:
            scanned += 1
            if scanned > _MAX_ENTITIES:
                truncated = True
                break
            layer_name = str(entity.dxf.layer) if entity.dxf.hasattr("layer") else "0"
            counts[layer_name] = counts.get(layer_name, 0) + 1
            kind = entity.dxftype()
            if kind in {"TEXT", "MTEXT", "ATTRIB"}:
                text_count += 1
                value = _entity_text(entity, kind)
                if value and len(texts) < _MAX_TEXTS:
                    texts.append(
                        DxfText(
                            space=space,
                            layer=layer_name,
                            kind=_text_kind(kind),
                            value=value[:_MAX_TEXT_CHARS],
                        )
                    )
            elif kind == "DIMENSION":
                dimension_count += 1
                if len(dimensions) < _MAX_DIMENSIONS:
                    dimensions.append(_dimension(entity, space, layer_name))
            elif kind == "INSERT":
                block_name = str(entity.dxf.name) if entity.dxf.hasattr("name") else ""
                if (
                    block_name
                    and not block_name.startswith("*")
                    and block_name not in seen_blocks
                ):
                    seen_blocks.add(block_name)
                    if len(blocks) < _MAX_BLOCKS:
                        blocks.append(block_name)
        if truncated:
            break

    ordered_names = table_names + [
        name for name in counts if name not in set(table_names)
    ]
    if (
        text_count > len(texts)
        or dimension_count > len(dimensions)
        or len(seen_blocks) > len(blocks)
        or len(ordered_names) > _MAX_LAYERS
    ):
        truncated = True

    layers = [
        DxfLayer(name=name, entity_count=counts.get(name, 0))
        for name in ordered_names[:_MAX_LAYERS]
    ]
    return DxfDrawing(
        units=units,
        layers=layers,
        texts=texts,
        dimensions=dimensions,
        blocks=blocks,
        text_count=text_count,
        dimension_count=dimension_count,
        block_count=len(seen_blocks),
        truncated=truncated,
    )


def _layouts(document: Drawing) -> Iterator[tuple[str, Layout]]:
    for layout in document.layouts:
        name = str(layout.name)
        yield ("model" if name.upper() == "MODEL" else name, layout)


def _units(document: Drawing) -> str:
    try:
        code = int(document.header["$INSUNITS"])
    except (KeyError, TypeError, ValueError):
        code = 0
    return _UNIT_NAMES.get(code, f"code {code}")


def _text_kind(dxftype: str) -> str:
    if dxftype == "MTEXT":
        return "mtext"
    if dxftype == "ATTRIB":
        return "attribute"
    return "text"


def _entity_text(entity: DXFEntity, kind: str) -> str:
    if kind == "MTEXT":
        return _mtext_value(entity)
    if entity.dxf.hasattr("text"):
        return str(entity.dxf.text).strip()
    return ""


def _mtext_value(entity: DXFEntity) -> str:
    from ezdxf.entities.mtext import MText

    if isinstance(entity, MText):
        plain = entity.plain_text()
        if isinstance(plain, list):
            return " ".join(plain).strip()
        return plain.strip()
    return ""


def _dimension(entity: DXFEntity, space: str, layer_name: str) -> DxfDimension:
    from ezdxf.entities.dimension import Dimension

    measurement: float | None = None
    if isinstance(entity, Dimension):
        try:
            raw = entity.get_measurement()
            measurement = float(raw) if isinstance(raw, (int, float)) else None
        except (TypeError, ValueError):
            measurement = None

    override: str | None = None
    if entity.dxf.hasattr("text"):
        raw_text = str(entity.dxf.text).strip()
        if raw_text and raw_text != "<>":
            override = raw_text[:_MAX_TEXT_CHARS]
    return DxfDimension(
        space=space,
        layer=layer_name,
        measurement=measurement,
        text_override=override,
    )
