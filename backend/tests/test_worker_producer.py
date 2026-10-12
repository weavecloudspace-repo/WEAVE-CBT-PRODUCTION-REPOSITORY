import os
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.workers.producer import (
    ArqProducer,
    durable_exam_job_id,
    roster_reconcile_job_id,
)


class ArqProducerDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_shot_exam_job_uses_deterministic_job_id(self):
        exam_id = str(uuid4())
        redis = AsyncMock()
        redis.enqueue_job.return_value = object()
        producer = ArqProducer()
        producer._redis = redis

        queued = await producer.enqueue("finalize_exam_close", exam_id)

        self.assertTrue(queued)
        redis.enqueue_job.assert_awaited_once_with(
            "finalize_exam_close",
            exam_id,
            _job_id=f"weave-cbt:finalize_exam_close:{exam_id}",
        )

    async def test_existing_deterministic_job_counts_as_scheduled(self):
        exam_id = str(uuid4())
        redis = AsyncMock()
        redis.enqueue_job.return_value = None
        producer = ArqProducer()
        producer._redis = redis

        queued = await producer.enqueue("sync_exam_results", exam_id)

        self.assertTrue(queued)

    async def test_repeatable_completion_evaluation_is_not_deduplicated(self):
        exam_id = str(uuid4())
        redis = AsyncMock()
        redis.enqueue_job.return_value = None
        producer = ArqProducer()
        producer._redis = redis

        queued = await producer.enqueue("evaluate_exam_completion", exam_id)

        self.assertFalse(queued)
        redis.enqueue_job.assert_awaited_once_with(
            "evaluate_exam_completion",
            exam_id,
        )
        self.assertIsNone(durable_exam_job_id("evaluate_exam_completion", exam_id))

    async def test_reconcile_is_not_globally_deduplicated_by_exam_id(self):
        exam_id = str(uuid4())
        redis = AsyncMock()
        redis.enqueue_job.return_value = None
        producer = ArqProducer()
        producer._redis = redis

        queued = await producer.enqueue("reconcile_exam_roster", exam_id)

        self.assertFalse(queued)
        redis.enqueue_job.assert_awaited_once_with(
            "reconcile_exam_roster",
            exam_id,
        )
        self.assertIsNone(durable_exam_job_id("reconcile_exam_roster", exam_id))

    def test_roster_reconciliation_id_is_scoped_to_roster_version(self):
        exam_id = str(uuid4())

        version_six = roster_reconcile_job_id(exam_id, 6)
        version_seven = roster_reconcile_job_id(exam_id, 7)

        self.assertEqual(
            version_six,
            f"weave-cbt:reconcile_exam_roster:{exam_id}:v6",
        )
        self.assertEqual(
            version_seven,
            f"weave-cbt:reconcile_exam_roster:{exam_id}:v7",
        )
        self.assertNotEqual(version_six, version_seven)

    async def test_same_roster_generation_can_be_explicitly_deduplicated(self):
        exam_id = str(uuid4())
        job_id = roster_reconcile_job_id(exam_id, 8)
        redis = AsyncMock()
        redis.enqueue_job.return_value = None
        producer = ArqProducer()
        producer._redis = redis

        queued = await producer.enqueue(
            "reconcile_exam_roster",
            exam_id,
            _job_id=job_id,
        )

        self.assertTrue(queued)
        redis.enqueue_job.assert_awaited_once_with(
            "reconcile_exam_roster",
            exam_id,
            _job_id=job_id,
        )


if __name__ == "__main__":
    unittest.main()
