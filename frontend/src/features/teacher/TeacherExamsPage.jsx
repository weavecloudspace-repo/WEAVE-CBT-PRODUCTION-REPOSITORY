import { buildAcademicLevels } from '../../shared/academics/authoringScope'
import { ExamLifecycleFilter } from '../../shared/exams/ExamLifecycleFilter'
import { currentExamRevisions } from '../../shared/exams/examLineage'
import { getAnchoredPopoverPosition } from '../../shared/ui/anchoredPopover'
import { useEffect, useMemo, useRef, useState } from "react";
import { ExamCard, ExamViewToggle } from '../../shared/exams/ExamCard';
import { canManageExam, examStatuses } from '../../shared/exams/examPermissions';
import '../../shared/exams/exam-workspace.css';
import { createPortal } from "react-dom";
import {
  RiAddLine,
  RiDeleteBinLine,
  RiEdit2Line,
  RiSearchLine,
} from "@remixicon/react";
import { Icon } from "../../shared/icons/Icon";
import { Notice, SelectControl } from "../../shared/ui";

const PAGE_SIZE = 12;
const EXAM_TABS = examStatuses;

export function TeacherExamsPage({ state, dispatch, teacherData, gateway }) {
  const [view, setView] = useState("grid");
  const [query, setQuery] = useState(() => teacherData.exams.find((exam) => exam.id === state.staff.selectedExamId)?.title || "");
  const [status, setStatus] = useState("all");
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState("all");
  const [componentId, setComponentId] = useState("all");
  const [requestedPage, setPage] = useState(1);
  const [menuExamId, setMenuExamId] = useState(null);
  const [menuPosition, setMenuPosition] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [lifecycleError, setLifecycleError] = useState("");
  const [busyExamId, setBusyExamId] = useState(null);
  const currentExams = useMemo(() => currentExamRevisions(teacherData.exams), [teacherData.exams])
  const menuRef = useRef(null);
  const actor = state.session?.actor;

  function closeMenu() {
    setMenuExamId(null);
    setMenuPosition(null);
  }

  useEffect(() => {
    if (!menuExamId) return undefined;

    const closeOutside = (event) => {
      if (!menuRef.current?.contains(event.target) && !event.target.closest?.('.teacher-exam-lifecycle__trigger')) closeMenu();
    };
    const closeEscape = (event) => {
      if (event.key === "Escape") closeMenu();
    };
    const closeViewport = (event) => { if (!menuRef.current?.contains(event.target) && !event.target.closest?.('.teacher-exam-lifecycle__trigger')) closeMenu(); };

    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    window.addEventListener("resize", closeViewport);
    window.addEventListener("scroll", closeViewport, true);

    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
      window.removeEventListener("resize", closeViewport);
      window.removeEventListener("scroll", closeViewport, true);
    };
  }, [menuExamId]);

  useEffect(() => {
    if (!pendingAction) return undefined;
    const closeEscape = (event) => {
      if (event.key === "Escape" && !busyExamId) { setPendingAction(null); setLifecycleError(""); }
    };
    document.addEventListener("keydown", closeEscape);
    return () => document.removeEventListener("keydown", closeEscape);
  }, [pendingAction, busyExamId]);

  const statusCounts = useMemo(() => {
    const counts = Object.fromEntries(EXAM_TABS.map((tab) => [tab, 0]));
    counts.all = currentExams.length;
    currentExams.forEach((exam) => {
      if (counts[exam.status] !== undefined) counts[exam.status] += 1;
    });
    return counts;
  }, [currentExams]);

  const levels = useMemo(() => buildAcademicLevels(teacherData.subjects), [teacherData.subjects])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return currentExams.filter((exam) => {
      if (levelId !== 'all' && exam.academicLevelId !== levelId) return false
      if (status !== "all" && exam.status !== status) return false;
      if (subjectId !== "all" && exam.curriculumSubjectId !== subjectId)
        return false;
      if (componentId !== "all" && exam.assessmentComponentId !== componentId)
        return false;
      if (!needle) return true;
      return `${exam.title} ${exam.subjectName} ${exam.assessmentName}`
        .toLowerCase()
        .includes(needle);
    });
  }, [componentId, query, status, subjectId, currentExams, levelId]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  const visibleExams = filtered.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE,
  );

  const applyFilter = (setter) => (value) => {
    setter(value);
    setPage(1);
  };

  const toggleMenu = (exam, trigger) => {
    if (menuExamId === exam.id) {
      closeMenu();
      return;
    }
    setMenuPosition(getAnchoredPopoverPosition(trigger, { width: 320, maxHeight: 400 }).style);
    setMenuExamId(exam.id);
  };

  const requestAction = (exam, action) => {
    closeMenu();
    setLifecycleError("");
    setPendingAction({ exam, action });
  };

  const closeConfirmation = () => {
    if (busyExamId) return;
    setPendingAction(null);
    setLifecycleError("");
  };

  const confirmLifecycle = async () => {
    if (!pendingAction) return;
    const { exam, action } = pendingAction;
    setLifecycleError("");
    setBusyExamId(exam.id);

    try {
      if (action === "submit") {
        await gateway.exams.submitExam(exam.id, exam.authoringVersion || 1);
      } else if (action === "delete") {
        await gateway.exams.deleteDraftExam(
          exam.id,
          exam.authoringVersion || 1,
        );
      }
      await teacherData.refresh();
      setPendingAction(null);
      dispatch({ type: "staff", patch: { selectedExamId: null } });
    } catch (requestError) {
      setLifecycleError(
        requestError.userMessage ||
          `Weave could not ${action} this examination.`,
      );
    } finally {
      setBusyExamId(null);
    }
  };

  const openCreate = () =>
    dispatch({
      type: "staff",
      patch: { section: "create-exam", selectedExamId: null },
    });

  const openEdit = (exam) => {
    closeMenu();
    dispatch({
      type: "staff",
      patch: { section: "create-exam", selectedExamId: exam.id },
    });
  };

  const subjectOptions = [
    { value: "all", label: "All subjects" },
    ...teacherData.subjects.filter((subject) => levelId === 'all' || subject.academicLevelId === levelId).map((subject) => ({
      value: subject.id,
      label: subject.name,
      description: levelId === 'all' ? [subject.academicLevelName, subject.code].filter(Boolean).join(' / ') : subject.code || undefined,
    })),
  ];
  const componentOptions = [
    { value: "all", label: "All components" },
    ...teacherData.assessmentComponents.map((component) => ({
      value: component.id,
      label: component.name,
      description: `${component.maximumScore} marks`,
    })),
  ];
  const confirmationCopy = pendingAction
    ? getLifecycleConfirmation(pendingAction.action)
    : null;

  return (
    <div className="teacher-reference-page teacher-exams-page">
      <div className="teacher-page-heading teacher-exams-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon">
              <Icon name="calendar" size={27} />
            </span>
            <h1>Examinations</h1>
          </div>
          <p>
            Build draft papers, track their progress, and keep each assessment
            tied to the synchronized academic context.
          </p>
        </div>
        <div className="exam-heading-actions">
          <ExamLifecycleFilter value={status} counts={statusCounts} onChange={applyFilter(setStatus)} />
          <button
            className="teacher-primary-action"
            type="button"
            onClick={openCreate}
          >
            <RiAddLine size={18} /> Create Exam
          </button>
        </div>
      </div>

      {teacherData.error && <Notice tone="danger">{teacherData.error}</Notice>}
      {teacherData.warning && (
        <Notice tone="warning">{teacherData.warning}</Notice>
      )}

      <div className="teacher-exam-filters teacher-exam-filters--refined exam-filters">
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={18} aria-hidden="true" />
          <input
            aria-label="Search examinations"
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="Search by title, subject, or assessment..."
          />
        </label>
        <SelectControl label="Academic level filter" value={levelId}
          options={[{ value: 'all', label: 'All levels' }, ...levels.map((level) => ({ value: level.id, label: level.name }))]}
          onChange={(value) => { setLevelId(value); setSubjectId('all'); setPage(1) }} />
        <SelectControl
          label="Exam subject filter"
          value={subjectId}
          options={subjectOptions}
          onChange={applyFilter(setSubjectId)}
        />
        <SelectControl
          label="Assessment component filter"
          value={componentId}
          options={componentOptions}
          onChange={applyFilter(setComponentId)}
        />
        <ExamViewToggle value={view} onChange={setView} />
      </div>

      <section
        className={`exam-collection exam-collection--${view}`}
        aria-busy={teacherData.loading}
        aria-label="Examinations"
      >
        {visibleExams.map((exam) => {
          const canManageDraft = canManageExam(exam, actor, teacherData.assignments);
          const eligibleContributor = Boolean(
            exam.status === 'draft' &&
            actor?.role === 'teacher' &&
            teacherData.assignments.some((assignment) => assignment.curriculumSubjectId === exam.curriculumSubjectId),
          );
          const canContributeManual = Boolean(
            !canManageDraft && eligibleContributor && exam.selectionMode === 'manual',
          );
          const contributionAction = canContributeManual ? (
            <button
              type="button"
              className="exam-card__contribute"
              onClick={() => openEdit(exam)}
            >
              <RiEdit2Line size={16} aria-hidden="true" />
              <span>Contribute questions</span>
            </button>
          ) : null;

          return (
            <ExamCard
              key={exam.id}
              exam={exam}
              onOpen={() => dispatch({ type: 'staff', patch: { section: 'exam-history', selectedExamId: exam.id } })}
              onEdit={canManageDraft ? () => openEdit(exam) : undefined}
              cardAction={contributionAction}
            >
              <div className="teacher-exam-lifecycle">
                <button
                  className="teacher-exam-lifecycle__trigger"
                  type="button"
                  aria-label={`Lifecycle actions for ${exam.title}`}
                  aria-haspopup="dialog"
                  aria-expanded={menuExamId === exam.id}
                  onClick={(event) => toggleMenu(exam, event.currentTarget)}
                >
                  <Icon name="moreVertical" size={19} />
                </button>

                {menuExamId === exam.id && menuPosition && (
                  createPortal(<div
                    ref={menuRef}
                    className="teacher-exam-lifecycle__menu"
                    role="dialog"
                    aria-label={`Lifecycle for ${exam.title}`}
                    style={menuPosition}
                  >
                    <div className="teacher-exam-lifecycle__heading">
                      <div>
                        <strong>Exam lifecycle</strong>
                        <span>{exam.statusLabel}</span>
                      </div>
                      <small>v{exam.authoringVersion || 1}</small>
                    </div>

                    {canManageDraft ? (
                      <>
                        <button type="button" onClick={() => openEdit(exam)}>
                          <RiEdit2Line size={18} />
                          <span>
                            <strong>Edit draft details</strong>
                            <small>
                              Update assessment, timing, instructions and
                              delivery settings.
                            </small>
                          </span>
                        </button>

                        <button
                          type="button"
                          onClick={() => requestAction(exam, "submit")}
                        >
                          <Icon name="submit" size={18} />
                          <span>
                            <strong>Submit for review</strong>
                            <small>
                              Finish teacher authoring and send the paper to
                              administration.
                            </small>
                          </span>
                        </button>

                        <button
                          type="button"
                          className="teacher-exam-lifecycle__danger"
                          onClick={() => requestAction(exam, "delete")}
                        >
                          <RiDeleteBinLine size={18} />
                          <span>
                            <strong>Delete draft</strong>
                            <small>Permanently remove this draft paper.</small>
                          </span>
                        </button>
                      </>
                    ) : (
                      <div className="teacher-exam-lifecycle__info">
                        <Icon name="info" size={18} />
                        <p>{canContributeManual
                          ? 'This shared draft uses Manual selection. The lead author manages the paper settings. Use Contribute questions on the exam card to add questions from the configured bank.'
                          : lifecycleMessage(exam)}</p>
                      </div>
                    )}
                  </div>, document.body)
                )}
              </div>
            </ExamCard>
          );
        })}

        {!teacherData.loading && visibleExams.length === 0 && (
          <div className="teacher-exam-collection__empty">
            <span>
              <Icon name="calendar" size={24} />
            </span>
            <strong>
              {currentExams.length === 0
                ? "No examinations yet"
                : "No examinations match these filters"}
            </strong>
            <p>
              {currentExams.length === 0
                ? "Create the first draft paper for your current teaching scope."
                : "Adjust the search, subject, component, or lifecycle filter."}
            </p>
          </div>
        )}

        {teacherData.loading && (
          <div className="teacher-exam-collection__empty">
            <strong>Loading examinations…</strong>
          </div>
        )}

        <div className="teacher-exam-pagination teacher-exam-pagination--refined">
          <span>
            {filtered.length === 0
              ? "0 exams"
              : `Showing ${(page - 1) * PAGE_SIZE + 1}–${Math.min(
                  page * PAGE_SIZE,
                  filtered.length,
                )} of ${filtered.length} exams`}
          </span>
          <div>
            <button
              type="button"
              aria-label="Previous page"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              ‹
            </button>
            <span>
              {page} / {pageCount}
            </span>
            <button
              type="button"
              aria-label="Next page"
              disabled={page === pageCount}
              onClick={() => setPage(page + 1)}
            >
              ›
            </button>
          </div>
        </div>
      </section>

      {pendingAction &&
        confirmationCopy &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="teacher-exam-confirm-backdrop"
            onMouseDown={(event) => {
              if (event.currentTarget === event.target) closeConfirmation();
            }}
          >
            <section
              className={`teacher-exam-confirm-modal ${
                pendingAction.action === "delete" ? "is-danger" : ""
              }`}
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="teacher-exam-confirm-title"
              aria-describedby="teacher-exam-confirm-description"
            >
              <div className="teacher-exam-confirm-modal__heading">
                <span>
                  {pendingAction.action === "delete" ? (
                    <RiDeleteBinLine size={22} />
                  ) : (
                    <Icon name="submit" size={22} />
                  )}
                </span>
                <div>
                  <h2 id="teacher-exam-confirm-title">
                    {confirmationCopy.title}
                  </h2>
                  <p id="teacher-exam-confirm-description">
                    {confirmationCopy.description}
                  </p>
                </div>
              </div>

              <div className="teacher-exam-confirm-modal__exam">
                <span>Examination</span>
                <strong>{pendingAction.exam.title}</strong>
                <small>
                  {pendingAction.exam.subjectName} ·{" "}
                  {pendingAction.exam.assessmentName}
                </small>
              </div>

              <p className="teacher-exam-confirm-modal__warning">
                {confirmationCopy.warning}
              </p>

              {lifecycleError && (
                <Notice tone="danger">{lifecycleError}</Notice>
              )}

              <div className="teacher-exam-confirm-modal__actions">
                <button
                  type="button"
                  className="teacher-exam-confirm-modal__cancel"
                  disabled={busyExamId === pendingAction.exam.id}
                  onClick={closeConfirmation}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={`teacher-exam-confirm-modal__confirm ${
                    pendingAction.action === "delete" ? "is-danger" : ""
                  }`}
                  disabled={busyExamId === pendingAction.exam.id}
                  onClick={confirmLifecycle}
                >
                  {busyExamId === pendingAction.exam.id
                    ? confirmationCopy.busyLabel
                    : confirmationCopy.confirmLabel}
                </button>
              </div>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}

function lifecycleMessage(exam) {
  if (exam.status === "draft") {
    if (exam.selectionMode === 'random') {
      return "This shared draft uses Random selection. The lead author manages the question bank, question count and paper settings. Questions are chosen automatically, so you do not need to add or configure questions.";
    }
    return "This is a shared draft. Only its lead author can edit metadata, submit it for review, or delete it.";
  }
  if (exam.status === "submitted") {
    return "This paper has been submitted for administrator review. Teacher authoring is now read-only.";
  }
  if (exam.status === "sealed") {
    return "This paper is sealed. Operational lifecycle controls belong to school administration.";
  }
  if (exam.status === "active" || exam.status === "suspended") {
    return "This examination is in its live operational lifecycle. Operational controls are managed by the administrator.";
  }
  if (exam.status === "closed") {
    return "This examination is closed and preserved as academic evidence.";
  }
  if (exam.status === "cancelled") {
    return "This examination revision was cancelled. Lifecycle recovery is an administrator operation.";
  }
  return "No teacher lifecycle action is available for this examination state.";
}

function getLifecycleConfirmation(action) {
  if (action === "delete") {
    return {
      title: "Delete this draft examination?",
      description: "This permanently removes the draft paper.",
      warning:
        "Deletion cannot be undone. If another author changed the draft since this page loaded, Weave will reject the request instead of deleting stale data.",
      confirmLabel: "Delete draft",
      busyLabel: "Deleting…",
    };
  }

  return {
    title: "Submit this examination for review?",
    description:
      "Teacher authoring will end and the paper will move to the submitted lifecycle state.",
    warning:
      "Weave validates the paper before submission. Incomplete manual selections, insufficient random-bank capacity, or stale authoring versions will be rejected safely.",
    confirmLabel: "Submit for review",
    busyLabel: "Submitting…",
  };
}
