"""Internal evidence contracts for paired drawing verification."""

from typing import Literal

from pydantic import BaseModel

from onyx.tools.models import DrawingMarkBox


class FocusedChangeConfirmation(BaseModel):
    duplicate_change_id: str | None = None
    before_text: str = ""
    after_text: str = ""
    same_feature: bool
    visible_difference: bool
    artifact_or_markup: bool
    before_observation: str
    after_observation: str


class ChangeObservation(BaseModel):
    status: Literal["confirmed", "unconfirmed"]
    before_text: str
    after_text: str
    original_box: DrawingMarkBox | None
    revised_box: DrawingMarkBox | None
    explanation: str


class RequestConfirmation(BaseModel):
    same_target: bool
    requested_action_supported: bool
    before_target_evidence: str
    requested_action: str
    observed_evidence: str
    change_satisfies_request: bool = False
