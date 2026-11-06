"""Run with python -m onyx.engineering.worker in the private environment."""

import hashlib
import signal
import threading
from uuid import UUID

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.engineering_review import (
    claim_review,
    finish_review,
    heartbeat,
    worker_input,
)
from onyx.engineering.config import REVIEW_ENABLED, private_review_llm
from onyx.engineering.processing import ReviewInputError, process_pair
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import TraceContentMode
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def run_claim(review_id: UUID, token: UUID) -> None:
    with get_session_with_current_tenant() as session:
        row = worker_input(session, review_id, token)
    if row is None:
        return
    cancellation = CancellationSignal()
    stopped = threading.Event()

    def renew() -> None:
        # This pilot runs one tenant. Context variables do not cross threads.
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
        while not stopped.wait(10):
            try:
                with get_session_with_current_tenant() as session:
                    if not heartbeat(session, review_id, token):
                        cancellation.cancel()
                        return
            except Exception:
                cancellation.cancel()
                return

    renewer = threading.Thread(target=renew, daemon=True, name="review-lease")
    renewer.start()
    try:
        with cancellation_scope(cancellation):
            store = get_default_file_store()
            with store.read_file(row.original_blob, mode="b") as source:
                original = source.read()
            with store.read_file(row.revised_blob, mode="b") as source:
                revised = source.read()
            if (
                hashlib.sha256(original).hexdigest() != row.original_sha256
                or hashlib.sha256(revised).hexdigest() != row.revised_sha256
            ):
                raise ReviewInputError("An input failed its integrity check")
            cancellation.check()
            llm = private_review_llm()
            # Private drawing content must never enter tracing exporters.
            with trace(
                "engineering_review", content_mode=TraceContentMode.METADATA_ONLY
            ):
                result = process_pair(
                    original, revised, row.original_name, row.revised_name, row.id, llm
                )
            cancellation.check()
            with get_session_with_current_tenant() as session:
                finish_review(
                    session,
                    review_id,
                    token,
                    result=result,
                    model_name=llm.config.model_name if llm else None,
                )
    except AgentCancelled:
        pass
    except Exception as error:
        # Only controlled validation messages may enter the record. Provider errors may contain IP.
        message = (
            str(error)
            if isinstance(error, ReviewInputError)
            else "Processing failed. Check the private inference service and submit a new review."
        )
        logger.warning(
            "Review processing failed: review_id=%s error_type=%s",
            review_id,
            type(error).__name__,
        )
        with get_session_with_current_tenant() as session:
            finish_review(session, review_id, token, error=message)
    finally:
        stopped.set()
        renewer.join(timeout=2)


def main() -> None:
    if not REVIEW_ENABLED or MULTI_TENANT:
        raise SystemExit(
            "Enable DEPTH_REVIEW_ENABLED in a single-tenant deployment first"
        )
    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    SqlEngine.init_engine(pool_size=3, max_overflow=2)
    shutdown = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    signal.signal(signal.SIGINT, lambda *_: shutdown.set())
    while not shutdown.is_set():
        try:
            with get_session_with_current_tenant() as session:
                claim = claim_review(session)
            if claim:
                run_claim(*claim)
            else:
                shutdown.wait(2)
        except Exception as error:
            logger.warning(
                "Review worker unavailable: error_type=%s", type(error).__name__
            )
            shutdown.wait(5)


if __name__ == "__main__":
    main()
