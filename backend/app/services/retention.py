"""Meeting data retention — user-initiated deletion and age-based purge."""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_PURGE_INTERVAL_SECONDS = 6 * 60 * 60


async def delete_job(workspace, storage, job_id: str) -> bool:
    """Delete a job's row and files. Raises JobBusyError while processing."""
    deleted = await asyncio.to_thread(workspace.delete, job_id)
    # Remove files even if the row was already gone, so a retry can clean up leftovers.
    await asyncio.to_thread(storage.delete_job_files, job_id)
    return deleted


def retention_days() -> int:
    try:
        return max(0, int(os.getenv("MEETING_RETENTION_DAYS", "0")))
    except ValueError:
        logger.warning("[Retention] MEETING_RETENTION_DAYS is not an integer — purge disabled")
        return 0


async def purge_expired(workspace, storage) -> int:
    days = retention_days()
    if not days:
        return 0
    removed = 0
    for job_id in await asyncio.to_thread(workspace.expired, days):
        if await delete_job(workspace, storage, job_id):
            removed += 1
    if removed:
        logger.info("[Retention] Purged %d meetings older than %d days", removed, days)
    return removed


async def run_purge_loop(workspace, storage) -> None:
    while True:
        try:
            await purge_expired(workspace, storage)
        except Exception:
            logger.exception("[Retention] Purge failed")
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
