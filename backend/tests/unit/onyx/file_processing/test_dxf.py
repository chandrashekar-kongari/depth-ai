from io import BytesIO, StringIO
from unittest.mock import patch

import ezdxf
import pytest

from onyx.file_processing.dxf import parse_dxf, summarize_dxf
from onyx.file_processing.extract_file_text import extract_file_text_locally
from onyx.file_processing.file_types import (
    DXF_MIME_TYPE,
    OnyxFileExtensions,
    guess_mime_type,
)


def _sample_dxf() -> bytes:
    document = ezdxf.new(dxfversion="R2010")
    document.header["$INSUNITS"] = 4
    model = document.modelspace()
    model.add_line((0, 0), (25.4, 0), dxfattribs={"layer": "OUTLINE"})
    model.add_text(
        "25.4",
        dxfattribs={"insert": (0, 0), "height": 2.5, "layer": "NOTES"},
    )
    dimension = model.add_linear_dim(
        base=(0, 10),
        p1=(0, 0),
        p2=(25.4, 0),
        dxfattribs={"layer": "DIMS"},
    )
    dimension.render()
    document.blocks.new("TITLE")
    model.add_blockref("TITLE", (0, 0))
    buffer = StringIO()
    document.write(buffer)
    return buffer.getvalue().encode()


def test_parse_dxf_separates_text_from_dimension_entities() -> None:
    drawing = parse_dxf(_sample_dxf())

    assert drawing.units == "millimeters"
    outline = next(layer for layer in drawing.layers if layer.name == "OUTLINE")
    assert outline.entity_count == 1
    text = next(item for item in drawing.texts if item.value == "25.4")
    assert text.kind == "text"
    assert text.layer == "NOTES"
    dimension = drawing.dimensions[0]
    assert dimension.measurement == pytest.approx(25.4)
    assert dimension.text_override is None
    assert "TITLE" in drawing.blocks


def test_dwg_bytes_are_rejected() -> None:
    with pytest.raises(ValueError, match="DWG"):
        parse_dxf(b"AC1027" + b"\x00" * 16)


def test_dxf_upload_extracts_a_summary() -> None:
    data = _sample_dxf()

    assert ".dxf" in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
    with patch("mimetypes.guess_type", return_value=(None, None)):
        assert guess_mime_type("bracket.dxf") == DXF_MIME_TYPE

    summary = extract_file_text_locally(BytesIO(data), "bracket.dxf")

    assert summary.strip()
    assert "millimeters" in summary
    assert summarize_dxf(data) == summary
