"""Associate visual interpretations with native marks without losing their source boxes."""

import re

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
            requested_value = visual[index].requested_value
            if (
                requested_value is None
                and len(associations[index]) == 1
                and not visual[index].ambiguity.strip()
                and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", primary.text.strip())
            ):
                requested_value = primary.text.strip()
            result.append(
                visual[index].model_copy(
                    update={
                        "text": primary.text,
                        "box": primary.box,
                        "span_id": primary.span_id or visual[index].span_id,
                        "requested_value": requested_value,
                    }
                )
            )
            emitted.add(index)
    result.extend(item for index, item in enumerate(visual) if index not in emitted)
    return result
