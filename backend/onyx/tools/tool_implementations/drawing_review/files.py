from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.user_file import get_file_id_by_user_file_id, get_user_file_metadata
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.utils import load_chat_file_by_id
from onyx.tools.models import ToolCallException


class ReviewFileLoader:
    """Read original bytes for files accessible to the current chat."""

    def __init__(self, user_file_ids: list[UUID], chat_file_ids: list[UUID]) -> None:
        self._user_file_ids = set(user_file_ids)
        self._chat_file_ids = set(chat_file_ids)
        self._chat_file_id_strings = {str(file_id) for file_id in chat_file_ids}

    def load(self, raw_file_id: str) -> tuple[bytes, str]:
        try:
            file_id = UUID(raw_file_id)
        except ValueError as error:
            raise ToolCallException(
                message=f"Invalid file_id: {raw_file_id}",
                llm_facing_message=f"'{raw_file_id}' is not a valid file UUID.",
            ) from error

        if file_id in self._user_file_ids:
            return _read_user_file(file_id)
        if file_id in self._chat_file_ids:
            chat_file = load_chat_file_by_id(str(file_id))
            return chat_file.content, chat_file.filename or str(file_id)

        # Chat uploads can expose a UserFile ID backed by an allowed blob.
        with get_session_with_current_tenant() as db_session:
            blob_id = get_file_id_by_user_file_id(str(file_id), db_session)
        if blob_id is not None and blob_id in self._chat_file_id_strings:
            return _read_user_file(file_id)

        raise ToolCallException(
            message=f"File {file_id} not in available files",
            llm_facing_message=(
                f"File '{file_id}' is not available. "
                "Use a file_id from the drawing file list or an attached image tag."
            ),
        )


def _read_user_file(user_file_id: UUID) -> tuple[bytes, str]:
    with get_session_with_current_tenant() as db_session:
        metadata = get_user_file_metadata(user_file_id, db_session)
    with get_default_file_store().read_file(metadata.file_id, mode="b") as file:
        return file.read(), metadata.name
