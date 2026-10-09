"""PostgreSQL contributor provenance required by exam revision and sealing."""

CONTRIBUTOR_TRIGGERS = {
    ("exam_question_selections", "trg_exam_selection_contributor"),
    ("exam_questions", "trg_exam_question_contributor"),
}
