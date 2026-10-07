"""Read models for administrator makeup review; no lifecycle mutations."""

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.domains.academics.models import AcademicClass, Curriculum, CurriculumSubject
from app.domains.attempts.models import ExamAttempt
from app.domains.candidates.models import CandidateMakeupAuthorization, ExamCandidate
from app.domains.exams.lineage import latest_exam_revision_clause
from app.domains.exams.models import Exam, ExamQuestion, ExamStatus
from app.domains.questions.models import Question
from app.domains.results.models import ExamResult


class MakeupReviewRepository:
    @staticmethod
    def candidate_from():
        latest = aliased(CandidateMakeupAuthorization)
        authorization_id = (
            select(latest.id)
            .where(latest.candidate_id == ExamCandidate.id)
            .order_by(latest.approved_at.desc(), latest.id.desc())
            .limit(1)
            .correlate(ExamCandidate)
            .scalar_subquery()
        )
        return (
            ExamCandidate.__table__.join(
                AcademicClass.__table__, AcademicClass.id == ExamCandidate.class_id
            )
            .outerjoin(
                CandidateMakeupAuthorization.__table__,
                CandidateMakeupAuthorization.id == authorization_id,
            )
            .outerjoin(
                ExamAttempt.__table__, ExamAttempt.candidate_id == ExamCandidate.id
            )
            .outerjoin(ExamResult.__table__, ExamResult.attempt_id == ExamAttempt.id)
        )

    @classmethod
    def candidate_query(cls, exam_id=None):
        query = (
            select(
                ExamCandidate,
                CandidateMakeupAuthorization,
                ExamAttempt,
                ExamResult,
                AcademicClass.display_name.label("class_name"),
            )
            .select_from(cls.candidate_from())
            .where(
                or_(
                    ExamAttempt.id.is_(None),
                    CandidateMakeupAuthorization.id.is_not(None),
                )
            )
        )
        return query.where(ExamCandidate.exam_id == exam_id) if exam_id else query

    @classmethod
    async def candidates(cls, db, exam_id, *, offset, limit):
        query = cls.candidate_query(exam_id)
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await db.execute(
                query.order_by(ExamCandidate.display_name, ExamCandidate.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return rows, total

    @classmethod
    def overview_query(cls):
        state = case(
            (ExamAttempt.status == "in_progress", "writing"),
            (ExamAttempt.status == "interrupted", "paused"),
            (ExamAttempt.status == "submitted", "completed"),
            (ExamAttempt.status == "terminated", "terminated"),
            (ExamCandidate.status == "blocked", "blocked"),
            (ExamCandidate.status == "withdrawn", "withdrawn"),
            (CandidateMakeupAuthorization.id.is_(None), "awaiting_approval"),
            (CandidateMakeupAuthorization.revoked_at.is_not(None), "revoked"),
            (CandidateMakeupAuthorization.consumed_at.is_not(None), "needs_review"),
            else_="approved",
        )
        source = (
            select(ExamCandidate.exam_id.label("exam_id"), state.label("state"))
            .select_from(
                cls.candidate_from().join(
                    Exam.__table__, Exam.id == ExamCandidate.exam_id
                )
            )
            .where(
                Exam.status == ExamStatus.CLOSED,
                latest_exam_revision_clause(),
                or_(
                    ExamAttempt.id.is_(None),
                    CandidateMakeupAuthorization.id.is_not(None),
                ),
            )
            .subquery()
        )
        states = (
            "awaiting_approval",
            "approved",
            "writing",
            "paused",
            "completed",
            "revoked",
            "needs_review",
            "terminated",
            "blocked",
            "withdrawn",
        )
        query = select(
            source.c.exam_id,
            func.count().label("total"),
            *[
                func.sum(case((source.c.state == value, 1), else_=0)).label(value)
                for value in states
            ],
        ).group_by(source.c.exam_id)
        return query

    @classmethod
    async def overview(cls, db):
        return list((await db.execute(cls.overview_query())).mappings().all())

    @staticmethod
    async def blockers(db, exam):
        curriculum = aliased(Curriculum)
        subject = aliased(CurriculumSubject)
        own_level = (
            select(curriculum.academic_level_id)
            .join(subject, subject.curriculum_id == curriculum.id)
            .where(subject.id == exam.curriculum_subject_id)
            .scalar_subquery()
        )
        return list(
            (
                await db.execute(
                    select(Exam.title)
                    .join(
                        CurriculumSubject,
                        CurriculumSubject.id == Exam.curriculum_subject_id,
                    )
                    .join(Curriculum, Curriculum.id == CurriculumSubject.curriculum_id)
                    .where(
                        Exam.session_id == exam.session_id,
                        Exam.term_id == exam.term_id,
                        Curriculum.academic_level_id == own_level,
                        Exam.scheduled_start_at.is_not(None),
                        Exam.status.notin_((ExamStatus.CLOSED, ExamStatus.CANCELLED)),
                        latest_exam_revision_clause(),
                    )
                    .order_by(Exam.scheduled_start_at, Exam.id)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    async def fresh_question_count(db, exam):
        used = exists().where(
            ExamQuestion.exam_id == exam.id,
            ExamQuestion.source_question_id == Question.id,
        )
        return int(
            await db.scalar(
                select(func.count(Question.id)).where(
                    Question.bank_id == exam.question_bank_id,
                    Question.is_active.is_(True),
                    ~used,
                )
            )
            or 0
        )
