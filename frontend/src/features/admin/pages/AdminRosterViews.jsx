import { useEffect, useMemo, useState } from 'react'
import { RiArrowLeftLine, RiArrowRightLine, RiSearchLine } from '@remixicon/react'
import { buildAcademicLevels, listSubjectsForLevel } from '../../../shared/academics/authoringScope'
import { Icon } from '../../../shared/icons/Icon'
import { Notice, SelectControl } from '../../../shared/ui'
import {
  partitionRosterExams,
  rosterHistoryDescription,
  rosterHistoryKind,
  rosterHistoryLabel,
} from '../rosterLineage'
import '../admin-rosters.css'
import '../admin-roster-history.css'

const CURRENT_PAGE_SIZE = 12
const HISTORY_GROUP_PAGE_SIZE = 6
const TRANSITIONAL_ROSTER_STATES = new Set(['pending', 'building', 'stale'])

export function AdminCurrentRostersPage({ adminData, onNavigate }) {
  const [query, setQuery] = useState('')
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState('all')
  const [requestedPage, setPage] = useState(1)

  const levels = useMemo(() => buildAcademicLevels(adminData.subjects), [adminData.subjects])
  const levelSubjects = useMemo(
    () => levelId === 'all' ? [] : listSubjectsForLevel(adminData.subjects, levelId),
    [adminData.subjects, levelId],
  )
  const presentation = useMemo(() => partitionRosterExams(adminData.exams), [adminData.exams])
  const currentRosters = presentation.current

  const refreshExams = adminData.refreshExams
  useEffect(() => {
    if (!currentRosters.some((exam) => TRANSITIONAL_ROSTER_STATES.has(exam.rosterStatus))) return undefined
    const timer = window.setInterval(() => {
      void refreshExams({ silent: true })
    }, 4000)
    return () => window.clearInterval(timer)
  }, [currentRosters, refreshExams])

  const filtered = useMemo(
    () => currentRosters.filter((exam) => rosterMatchesFilters(exam, { query, levelId, subjectId })),
    [currentRosters, levelId, query, subjectId],
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / CURRENT_PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)
  const visible = filtered.slice((page - 1) * CURRENT_PAGE_SIZE, page * CURRENT_PAGE_SIZE)

  const levelOptions = [
    { value: 'all', label: 'All levels' },
    ...levels.map((level) => ({ value: level.id, label: level.name })),
  ]
  const subjectOptions = [
    { value: 'all', label: 'All subjects' },
    ...levelSubjects.map((subject) => ({ value: subject.id, label: subject.name, description: subject.code || undefined })),
  ]

  const changeLevel = (nextLevelId) => {
    setLevelId(nextLevelId)
    setSubjectId('all')
    setPage(1)
  }

  return (
    <div className="teacher-reference-page admin-rosters-page">
      <div className="teacher-page-heading admin-rosters-heading admin-rosters-heading--with-action">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="roster" size={27} /></span>
            <h1>Roster</h1>
          </div>
          <p>Review the current roster for each examination that is preparing, running, or finalizing.</p>
        </div>
        <button
          className="admin-roster-history-link"
          type="button"
          onClick={() => onNavigate('roster-history')}
        >
          View roster history
          <RiArrowRightLine size={17} aria-hidden="true" />
        </button>
      </div>

      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}

      <RosterFilters
        query={query}
        setQuery={(value) => { setQuery(value); setPage(1) }}
        levelId={levelId}
        changeLevel={changeLevel}
        subjectId={subjectId}
        setSubjectId={(value) => { setSubjectId(value); setPage(1) }}
        levelOptions={levelOptions}
        subjectOptions={subjectOptions}
      />

      <section className="admin-roster-section" aria-labelledby="current-rosters-title">
        <div className="admin-roster-section__heading">
          <div>
            <h2 id="current-rosters-title">Current rosters</h2>
            <p>Only the latest operational revision of each examination appears here.</p>
          </div>
          <span>{filtered.length} {filtered.length === 1 ? 'roster' : 'rosters'}</span>
        </div>

        <div className="admin-roster-grid" aria-label="Current examination rosters" aria-busy={adminData.loading}>
          {visible.map((exam) => (
            <RosterCard
              key={exam.id}
              exam={exam}
              onOpen={() => onNavigate('roster-detail', { selectedExamId: exam.id })}
            />
          ))}

          {!adminData.loading && visible.length === 0 && (
            <div className="admin-roster-empty">
              <span><Icon name="roster" size={27} /></span>
              <div>
                <strong>{currentRosters.length ? 'No current rosters match these filters' : 'No current prepared rosters'}</strong>
                <p>{currentRosters.length ? 'Adjust the level, subject, or search filters.' : 'A latest examination revision appears here after its roster is prepared.'}</p>
              </div>
            </div>
          )}
          {adminData.loading && <div className="admin-roster-empty"><div><strong>Loading examination rosters…</strong></div></div>}
        </div>

        <RosterPagination
          page={page}
          pageCount={pageCount}
          total={filtered.length}
          pageSize={CURRENT_PAGE_SIZE}
          label="rosters"
          onPrevious={() => setPage(page - 1)}
          onNext={() => setPage(page + 1)}
        />
      </section>
    </div>
  )
}

export function AdminRosterHistoryPage({ adminData, onNavigate }) {
  const [query, setQuery] = useState('')
  const [levelId, setLevelId] = useState('all')
  const [subjectId, setSubjectId] = useState('all')
  const [historyType, setHistoryType] = useState('all')
  const [requestedPage, setPage] = useState(1)

  const levels = useMemo(() => buildAcademicLevels(adminData.subjects), [adminData.subjects])
  const levelSubjects = useMemo(
    () => levelId === 'all' ? [] : listSubjectsForLevel(adminData.subjects, levelId),
    [adminData.subjects, levelId],
  )
  const historyGroups = useMemo(
    () => partitionRosterExams(adminData.exams).historyGroups,
    [adminData.exams],
  )
  const filteredGroups = useMemo(
    () => historyGroups
      .map((group) => ({
        ...group,
        entries: group.entries.filter((exam) => {
          if (!rosterMatchesFilters(exam, { query, levelId, subjectId })) return false
          if (historyType === 'all') return true
          return rosterHistoryKind(exam, adminData.exams) === historyType
        }),
      }))
      .filter((group) => group.entries.length > 0),
    [adminData.exams, historyGroups, historyType, levelId, query, subjectId],
  )

  const pageCount = Math.max(1, Math.ceil(filteredGroups.length / HISTORY_GROUP_PAGE_SIZE))
  const page = Math.min(requestedPage, pageCount)
  const visibleGroups = filteredGroups.slice(
    (page - 1) * HISTORY_GROUP_PAGE_SIZE,
    page * HISTORY_GROUP_PAGE_SIZE,
  )
  const filteredRosterCount = filteredGroups.reduce((total, group) => total + group.entries.length, 0)

  const levelOptions = [
    { value: 'all', label: 'All levels' },
    ...levels.map((level) => ({ value: level.id, label: level.name })),
  ]
  const subjectOptions = [
    { value: 'all', label: 'All subjects' },
    ...levelSubjects.map((subject) => ({ value: subject.id, label: subject.name, description: subject.code || undefined })),
  ]
  const historyTypeOptions = [
    { value: 'all', label: 'All history' },
    { value: 'superseded', label: 'Superseded revisions' },
    { value: 'closed', label: 'Closed exams' },
    { value: 'cancelled', label: 'Cancelled exams' },
  ]

  const resetPage = () => setPage(1)
  const changeLevel = (nextLevelId) => {
    setLevelId(nextLevelId)
    setSubjectId('all')
    resetPage()
  }

  return (
    <div className="teacher-reference-page admin-rosters-page admin-roster-history-page">
      <button className="admin-roster-back" type="button" onClick={() => onNavigate('roster')}>
        <RiArrowLeftLine size={17} /> Back to current rosters
      </button>

      <div className="teacher-page-heading admin-rosters-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="roster" size={27} /></span>
            <h1>Roster history</h1>
          </div>
          <p>Review superseded revisions and completed or cancelled roster snapshots. Candidate lists remain available for audit.</p>
        </div>
      </div>

      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}

      <div className="admin-roster-history-filters">
        <label className="teacher-search-control teacher-search-control--grow">
          <RiSearchLine size={18} aria-hidden="true" />
          <input
            aria-label="Search roster history"
            type="search"
            value={query}
            onChange={(event) => { setQuery(event.target.value); resetPage() }}
            placeholder="Search exam, level, subject, assessment, or revision..."
          />
        </label>
        <SelectControl label="Roster history level filter" value={levelId} options={levelOptions} onChange={changeLevel} />
        <SelectControl
          label="Roster history subject filter"
          value={subjectId}
          options={subjectOptions}
          onChange={(value) => { setSubjectId(value); resetPage() }}
          disabled={levelId === 'all'}
        />
        <SelectControl
          label="Roster history type filter"
          value={historyType}
          options={historyTypeOptions}
          onChange={(value) => { setHistoryType(value); resetPage() }}
        />
      </div>

      <section className="admin-roster-history admin-roster-history--standalone" aria-labelledby="roster-history-title">
        <div className="admin-roster-section__heading admin-roster-history__heading">
          <div>
            <h2 id="roster-history-title">Historical rosters</h2>
            <p>Previous revisions are grouped with their examination lineage for easier review.</p>
          </div>
          <span>{filteredRosterCount} {filteredRosterCount === 1 ? 'roster' : 'rosters'}</span>
        </div>

        {!adminData.loading && visibleGroups.length === 0 && (
          <div className="admin-roster-empty admin-roster-history__empty">
            <span><Icon name="roster" size={27} /></span>
            <div>
              <strong>{historyGroups.length ? 'No roster history matches these filters' : 'No roster history yet'}</strong>
              <p>{historyGroups.length ? 'Adjust the history type, level, subject, or search filters.' : 'Superseded revisions and terminal exam rosters will be retained here.'}</p>
            </div>
          </div>
        )}

        {visibleGroups.map((group) => (
          <RosterHistoryGroup
            key={group.id}
            group={group}
            allExams={adminData.exams}
            onNavigate={onNavigate}
          />
        ))}

        {filteredGroups.length > 0 && (
          <RosterPagination
            page={page}
            pageCount={pageCount}
            total={filteredGroups.length}
            pageSize={HISTORY_GROUP_PAGE_SIZE}
            label="exam groups"
            onPrevious={() => setPage(page - 1)}
            onNext={() => setPage(page + 1)}
          />
        )}
      </section>
    </div>
  )
}

function RosterFilters({ query, setQuery, levelId, changeLevel, subjectId, setSubjectId, levelOptions, subjectOptions }) {
  return (
    <div className="admin-roster-filters">
      <label className="teacher-search-control teacher-search-control--grow">
        <RiSearchLine size={18} aria-hidden="true" />
        <input
          aria-label="Search rosters"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by exam, level, subject, or assessment..."
        />
      </label>
      <SelectControl label="Roster level filter" value={levelId} options={levelOptions} onChange={changeLevel} />
      <SelectControl
        label="Roster subject filter"
        value={subjectId}
        options={subjectOptions}
        onChange={setSubjectId}
        disabled={levelId === 'all'}
      />
    </div>
  )
}

function RosterHistoryGroup({ group, allExams, onNavigate }) {
  const scope = [group.academicLevelName, group.subjectName, group.assessmentName].filter(Boolean).join(' · ')
  return (
    <article className="admin-roster-history-group">
      <div className="admin-roster-history-group__heading">
        <div>
          <span>Exam lineage</span>
          <h3>{group.title}</h3>
          <p>{scope || 'Historical examination rosters'}</p>
        </div>
        <strong>{group.entries.length} historical {group.entries.length === 1 ? 'roster' : 'rosters'}</strong>
      </div>
      <div className="admin-roster-grid admin-roster-history-group__grid">
        {group.entries.map((exam) => (
          <RosterCard
            key={exam.id}
            exam={exam}
            historical
            allExams={allExams}
            onOpen={() => onNavigate('roster-detail', { selectedExamId: exam.id })}
          />
        ))}
      </div>
    </article>
  )
}

function RosterCard({ exam, historical = false, allExams = [], onOpen }) {
  const historyKind = historical ? rosterHistoryKind(exam, allExams) : null
  const statusCopy = historical
    ? rosterHistoryDescription(exam, allExams)
    : rosterStatusCopy(exam.rosterStatus)
  const statusLabel = historical ? rosterHistoryLabel(historyKind) : exam.statusLabel
  const statusValue = historical ? historyKind : exam.status

  return (
    <article className={`admin-roster-card${historical ? ' admin-roster-card--historical' : ''}`}>
      <button className="admin-roster-card__open" type="button" onClick={onOpen} aria-label={`${historical ? 'Open historical roster' : 'Open roster'} for ${exam.title} revision ${exam.revisionNumber || 1}`}>
        <div className="admin-roster-card__top">
          <span className="admin-roster-ledger"><Icon name="roster" size={28} /></span>
          <RosterLifecycleState status={statusValue} label={statusLabel} />
        </div>
        <div className="admin-roster-card__scope">{[exam.academicLevelName, exam.subjectName].filter(Boolean).join(' · ') || 'Examination roster'}</div>
        <h2>{exam.title}</h2>
        <p>{exam.assessmentName} · Revision {exam.revisionNumber || 1}</p>
        <div className="admin-roster-card__status-copy">{statusCopy}</div>
        <div className="admin-roster-card__meta">
          <div><span>{historical ? 'Candidates' : 'Current candidates'}</span><strong>{exam.rosterCandidateCount || 0}</strong></div>
          <div><span>Roster version</span><strong>v{exam.rosterVersion || 0}</strong></div>
        </div>
        <div className="admin-roster-card__footer">
          <span>{exam.scheduledStartAt ? formatCompactDate(exam.scheduledStartAt) : 'Schedule not set'}</span>
          <strong>{historical ? 'View historical roster' : 'View roster'} <RiArrowRightLine size={16} aria-hidden="true" /></strong>
        </div>
      </button>
    </article>
  )
}

function RosterLifecycleState({ status, label }) {
  const normalized = String(status || 'historical').toLowerCase()
  return <span className={`admin-roster-lifecycle-state admin-roster-lifecycle-state--${normalized}`}>{label || titleCase(normalized)}</span>
}

function RosterPagination({ page, pageCount, total, pageSize, label, onPrevious, onNext }) {
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, total)
  return (
    <div className="admin-roster-pagination">
      <span>{total === 0 ? `0 ${label}` : `Showing ${start}–${end} of ${total} ${label}`}</span>
      <div>
        <button type="button" aria-label={`Previous ${label} page`} disabled={page === 1} onClick={onPrevious}>‹</button>
        <span>{page} / {pageCount}</span>
        <button type="button" aria-label={`Next ${label} page`} disabled={page === pageCount} onClick={onNext}>›</button>
      </div>
    </div>
  )
}

function rosterMatchesFilters(exam, { query, levelId, subjectId }) {
  if (levelId !== 'all' && exam.academicLevelId !== levelId) return false
  if (subjectId !== 'all' && exam.curriculumSubjectId !== subjectId) return false
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return `${exam.title} ${exam.academicLevelName} ${exam.subjectName} ${exam.assessmentName} revision ${exam.revisionNumber || 1}`.toLowerCase().includes(needle)
}

function rosterStatusCopy(status) {
  if (status === 'pending') return 'Waiting for candidate preparation.'
  if (status === 'building') return 'Building the candidate snapshot.'
  if (status === 'stale') return 'Enrollment changed; refreshing automatically.'
  if (status === 'failed') return 'Roster needs administrator attention.'
  if (status === 'ready') return 'Candidate snapshot is ready for this sitting.'
  return 'Roster has not been prepared.'
}

function titleCase(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatCompactDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
