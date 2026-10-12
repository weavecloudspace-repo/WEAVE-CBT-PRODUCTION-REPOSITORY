from __future__ import annotations

import inspect
import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.database import Base
from app.domains.academics.models import (
    AcademicClass,
    AcademicLevel,
    ArmLabel,
    ClassTermDepartment,
    Curriculum,
    CurriculumSubject,
    CurriculumSubjectDepartment,
    StudentEnrollment,
    TeacherAssignment,
)
from app.domains.academics.repository import AcademicRepository
from app.domains.exams.models import Exam, ExamTargetClass
from app.domains.exams.repository import ExamRepository
from app.domains.questions.models import QuestionBank
from app.domains.questions.repository import QuestionRepository


class AcademicProjectionContractTests(unittest.TestCase):
    def test_level_matches_weave_v5_contract(self) -> None:
        columns = set(AcademicLevel.__table__.c.keys())
        self.assertTrue(
            {
                "id",
                "name",
                "category",
                "position",
                "specialization_required_from_term_position",
                "synced_at",
            }
            <= columns
        )
        self.assertNotIn("weave_level_id", columns)
        self.assertNotIn("is_terminal", columns)

    def test_arm_labels_are_preserved_locally(self) -> None:
        self.assertEqual(ArmLabel.__tablename__, "arm_labels")
        self.assertIn("label", ArmLabel.__table__.c)

    def test_class_uses_level_and_arm_label(self) -> None:
        columns = set(AcademicClass.__table__.c.keys())
        self.assertTrue(
            {"academic_level_id", "arm_label_id", "display_name", "is_active"}
            <= columns
        )
        self.assertNotIn("arm", columns)
        self.assertNotIn("department_id", columns)

    def test_specialization_is_term_scoped(self) -> None:
        columns = set(ClassTermDepartment.__table__.c.keys())
        self.assertTrue({"class_id", "academic_term_id", "department_id"} <= columns)

    def test_curriculum_replaces_level_subject(self) -> None:
        self.assertIn("academic_level_id", Curriculum.__table__.c)
        columns = set(CurriculumSubject.__table__.c.keys())
        self.assertTrue(
            {"curriculum_id", "subject_id", "is_elective", "is_active"} <= columns
        )

    def test_curriculum_subject_department_replaces_subject_offering(self) -> None:
        columns = set(CurriculumSubjectDepartment.__table__.c.keys())
        self.assertTrue({"curriculum_subject_id", "department_id"} <= columns)
        self.assertNotIn("academic_term_id", columns)
        self.assertNotIn("subject_offerings", Base.metadata.tables)
        self.assertTrue(
            callable(AcademicRepository.list_curriculum_subject_departments)
        )
        self.assertTrue(
            callable(AcademicRepository.curriculum_subject_has_department_scope)
        )

    def test_teacher_assignment_is_time_safe_and_curriculum_subject_scoped(
        self,
    ) -> None:
        columns = set(TeacherAssignment.__table__.c.keys())
        self.assertTrue(
            {
                "teacher_membership_id",
                "class_id",
                "curriculum_subject_id",
                "effective_from",
                "effective_to",
            }
            <= columns
        )
        self.assertNotIn("is_active", columns)
        self.assertNotIn("level_subject_id", columns)

        indexes = {index.name for index in TeacherAssignment.__table__.indexes}
        self.assertIn("ix_teacher_assignments_live_teacher_effective", indexes)
        self.assertIn("ix_teacher_assignments_live_scope_effective", indexes)
        self.assertIn("ix_teacher_assignments_effective_from", indexes)
        self.assertIn("ix_teacher_assignments_effective_to", indexes)

    def test_enrollment_matches_bootstrap_contract_and_has_live_indexes(self) -> None:
        columns = set(StudentEnrollment.__table__.c.keys())
        self.assertTrue(
            {
                "student_id",
                "admission_number",
                "academic_level_id",
                "class_id",
                "academic_session_id",
                "is_current",
                "student_status",
            }
            <= columns
        )
        self.assertNotIn("weave_enrollment_id", columns)
        self.assertNotIn("outcome", columns)

        indexes = {index.name for index in StudentEnrollment.__table__.indexes}
        self.assertIn("uq_student_enrollments_current_student", indexes)
        self.assertIn("ix_student_enrollments_live_class", indexes)
        self.assertIn("ix_student_enrollments_live_session", indexes)

    def test_question_bank_is_curriculum_subject_scoped(self) -> None:
        columns = set(QuestionBank.__table__.c.keys())
        self.assertIn("curriculum_subject_id", columns)
        self.assertNotIn("level_subject_id", columns)
        params = inspect.signature(
            QuestionRepository.get_bank_by_scope_and_name
        ).parameters
        self.assertIn("curriculum_subject_id", params)

    def test_exam_target_freezes_class_without_legacy_offering(self) -> None:
        exam_columns = set(Exam.__table__.c.keys())
        target_columns = set(ExamTargetClass.__table__.c.keys())
        self.assertIn("curriculum_subject_id", exam_columns)
        self.assertNotIn("level_subject_id", exam_columns)
        self.assertNotIn("subject_offering_id", target_columns)
        self.assertIn("teacher_assignment_id", target_columns)
        self.assertNotIn("weave_teacher_assignment_id", target_columns)

    def test_repository_contracts_use_v5_projection_primitives(self) -> None:
        assignment = inspect.signature(
            AcademicRepository.get_active_assignment_for_scope
        ).parameters
        self.assertIn("teacher_membership_id", assignment)
        self.assertIn("class_id", assignment)
        self.assertIn("curriculum_subject_id", assignment)
        self.assertNotIn("level_subject_id", assignment)

        enrollments = inspect.signature(
            AcademicRepository.list_current_enrollments_for_class
        ).parameters
        self.assertIn("academic_session_id", enrollments)

        exams = inspect.signature(ExamRepository.list_exams).parameters
        self.assertIn("curriculum_subject_id", exams)
        self.assertNotIn("level_subject_id", exams)


if __name__ == "__main__":
    unittest.main()
