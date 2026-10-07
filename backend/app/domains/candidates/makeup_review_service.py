"""Administrator makeup projections over the existing authorization lifecycle."""

from datetime import UTC, datetime

from app.domains.attempts.models import AttemptStatus
from app.domains.attempts.query_service import AttemptQueryService
from app.domains.attempts.runtime_repository import AttemptRuntimeRepository
from app.domains.candidates.makeup_review_repository import MakeupReviewRepository
from app.domains.candidates.models import CandidateStatus
from app.domains.candidates.service import CandidateService
from app.domains.exams.exceptions import ExamNotFound
from app.domains.exams.models import ExamStatus
from app.domains.exams.repository import ExamRepository


class MakeupReviewService:
    @staticmethod
    def state(candidate, authorization, attempt):
        if attempt is not None:
            return {
                AttemptStatus.IN_PROGRESS: "writing",
                AttemptStatus.INTERRUPTED: "paused",
                AttemptStatus.SUBMITTED: "completed",
                AttemptStatus.TERMINATED: "terminated",
            }[attempt.status]
        if candidate.status != CandidateStatus.ELIGIBLE:
            return candidate.status.value
        if authorization is None:
            return "awaiting_approval"
        if authorization.revoked_at is not None:
            return "revoked"
        if authorization.consumed_at is not None:
            return "needs_review"
        return "approved"

    @classmethod
    async def overview(cls, db, *, actor):
        CandidateService._require_admin(actor)
        return {"exams": await MakeupReviewRepository.overview(db)}

    @classmethod
    async def detail(cls, db, *, actor, exam_id, offset, limit):
        CandidateService._require_admin(actor)
        exam = await ExamRepository.get_exam_by_id(db, exam_id)
        if exam is None:
            raise ExamNotFound("Examination does not exist")
        if exam.status != ExamStatus.CLOSED:
            raise ValueError(
                "Makeups can only be reviewed after the original examination is closed"
            )
        blockers = await MakeupReviewRepository.blockers(db, exam)
        fresh_count = await MakeupReviewRepository.fresh_question_count(db, exam)
        rows, total = await MakeupReviewRepository.candidates(
            db, exam_id, offset=offset, limit=limit
        )
        suspensions = await AttemptRuntimeRepository.list_exam_suspensions(db, exam_id)
        now = datetime.now(UTC)
        return {
            "exam_id": exam_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "blockers": blockers,
            "fresh_question_count": fresh_count,
            "required_question_count": exam.question_count,
            "available": not blockers and fresh_count >= exam.question_count,
            "candidates": [
                {
                    "id": candidate.id,
                    "name": candidate.display_name,
                    "admission_number": candidate.admission_number,
                    "class_name": class_name,
                    "state": cls.state(candidate, authorization, attempt),
                    "authorization_id": authorization.id if authorization else None,
                    "reason": authorization.reason if authorization else None,
                    "can_approve": candidate.status == CandidateStatus.ELIGIBLE
                    and attempt is None
                    and (authorization is None or authorization.revoked_at is not None),
                    "can_revoke": authorization is not None
                    and authorization.revoked_at is None
                    and authorization.consumed_at is None
                    and attempt is None,
                    "remaining_seconds": AttemptQueryService._remaining_seconds(
                        attempt, suspensions=suspensions, at=now
                    )
                    if attempt
                    else None,
                    "percentage": str(result.percentage) if result else None,
                }
                for candidate, authorization, attempt, result, class_name in rows
            ],
        }
