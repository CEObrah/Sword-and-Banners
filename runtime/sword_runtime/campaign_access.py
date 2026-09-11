"""Isolation for a complete runtime operation, including planning and reads."""
from contextlib import contextmanager
from functools import wraps

from sword_runtime.tx.locking import CampaignLock


@contextmanager
def campaign_access(runtime):
    coordinator = runtime.coordinator
    with CampaignLock(coordinator.lock_path, timeout=coordinator.lock_timeout) as lock:
        if lock.outermost:
            # A prior process may have died between file replacements. Finish or
            # roll back its WAL before exposing any owner, even on a read request.
            coordinator._recover_locked()
            coordinator.git.assert_pristine()
            # Some projections consult planner helpers. Cached owners from an
            # earlier revision must not survive into the next public operation.
            runtime.planner._reset()
        yield


def isolated_runtime(method):
    @wraps(method)
    def isolated(self, *args, **kwargs):
        with campaign_access(self):
            return method(self, *args, **kwargs)
    return isolated


def isolated_public_operation(runtime, method):
    @wraps(method)
    def isolated(*args, **kwargs):
        # Import lazily: OperationError lives in the caller's module.
        from sword_runtime.api.operations import OperationError
        from sword_runtime.tx.errors import (
            DirtyRepositoryError, IdempotencyConflictError, LockUnavailableError,
            RecoveryError, RemoteDurabilityError,
        )
        try:
            with campaign_access(runtime):
                return method(*args, **kwargs)
        except IdempotencyConflictError as exc:
            raise OperationError(409, "idempotency_conflict") from exc
        except LockUnavailableError as exc:
            raise OperationError(503, "campaign_writer_busy") from exc
        except (DirtyRepositoryError, RecoveryError, RemoteDurabilityError) as exc:
            raise OperationError(503, "campaign_unavailable") from exc
    return isolated
