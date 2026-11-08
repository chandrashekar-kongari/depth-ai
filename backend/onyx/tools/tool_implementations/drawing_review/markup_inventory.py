"""Associate visual interpretations with native marks without losing their source boxes."""

import re
from decimal import Decimal

from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
)


def merge_markups(
    native: list[ExtractedComment], visual: list[ExtractedComment]
) -> list[ExtractedComment]:
    associations: list[set[int]] = []
    for item in visual:
        indices = {
            index for index in range(len(native)) if f"n{index + 1}" in item.native_ids
        }
        if not indices and item.requested_value:
            value = item.requested_value.strip()
            candidates = [
                index for index, mark in enumerate(native) if mark.text.strip() == value
            ]
            interpretations = [
                mark for mark in visual if mark.requested_value == item.requested_value
            ]
            if len(candidates) == 1 and len(interpretations) == 1:
                indices = set(candidates)
        associations.append(indices)
    result: list[ExtractedComment] = []
    emitted: set[int] = set()
    for native_index, mark in enumerate(native):
        linked = [
            index
            for index, indices in enumerate(associations)
            if native_index in indices
        ]
        if not linked:
            result.append(mark)
            continue
        for index in linked:
            if index in emitted:
                continue
            primary = native[min(associations[index])]
            interpreted = visual[index]
            requested_value = interpreted.requested_value
            request = interpreted.request
            native_value = primary.text.strip()
            single_mark = len(associations[index]) == 1
            single_numeric = single_mark and re.fullmatch(
                r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", native_value
            )
            if single_numeric and (
                requested_value is not None
                or primary.requested_value is not None
                or not interpreted.ambiguity.strip()
            ):
                if requested_value and (
                    not re.fullmatch(
                        r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", requested_value.strip()
                    )
                    or Decimal(requested_value) != Decimal(native_value)
                ):
                    request = f"Set the marked dimension to {native_value}."
                requested_value = native_value
            if single_mark and primary.bracket is not None:
                request = f"Set the bracketed {primary.bracket.axis} dimension to {native_value}."
            result.append(
                interpreted.model_copy(
                    update={
                        "text": primary.text,
                        "box": primary.box,
                        "target_box": primary.target_box if single_mark else None,
                        "bracket": primary.bracket if single_mark else None,
                        "span_id": primary.span_id or interpreted.span_id,
                        "request": request,
                        "requested_value": requested_value,
                    }
                )
            )
            emitted.add(index)
    result.extend(item for index, item in enumerate(visual) if index not in emitted)
    return result
