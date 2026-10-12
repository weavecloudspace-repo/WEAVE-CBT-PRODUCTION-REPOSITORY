import { useState } from 'react'
import { buildAcademicLevels } from '../../../shared/academics/authoringScope'
import { currentExamRevisions } from '../../../shared/exams/examLineage'
import { Icon } from '../../../shared/icons/Icon'
import { Notice, SelectControl } from '../../../shared/ui'
import '../admin-timetable.css'
import { AdminDatePicker } from '../AdminDatePicker'

const dateFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' })

const localDateKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
export function AdminTimetablePage({ adminData, levelId = null, onSelectLevel }) {
  const [selectedDay, setSelectedDay] = useState(() => localDateKey(new Date()))
  const [levelFilter, setLevelFilter] = useState('all')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState('')
  const levels = buildAcademicLevels(adminData.subjects)
  const visibleLevels = levels.filter((level) => levelFilter === 'all' || level.id === levelFilter)
  const allScheduled = currentExamRevisions(adminData.exams)
    .filter((exam) => exam.scheduledStartAt && Number.isFinite(Date.parse(exam.scheduledStartAt))
      && ['draft', 'submitted', 'sealed'].includes(exam.status)
      && localDateKey(new Date(exam.scheduledStartAt)) === selectedDay)
    .sort((a, b) => Date.parse(a.scheduledStartAt) - Date.parse(b.scheduledStartAt) || a.title.localeCompare(b.title))
  const scheduled = allScheduled.filter((exam) => exam.academicLevelId === levelId)
  const days = new Map()
  for (const exam of scheduled) {
    const date = new Date(exam.scheduledStartAt)
    const day = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
    if (!days.has(day)) days.set(day, { date, exams: [] })
    days.get(day).exams.push(exam)
  }
  const levelName = levels.find((level) => level.id === levelId)?.name || 'Academic level'
  const issue = refreshError || adminData.error || adminData.warning
  const refresh = async () => {
    setRefreshing(true)
    setRefreshError('')
    try { await adminData.refresh() }
    catch (error) { setRefreshError(error.userMessage || 'Could not refresh the timetable. Please try again.') }
    finally { setRefreshing(false) }
  }

  return (
    <div className="teacher-reference-page admin-timetable">
      <header className="teacher-page-heading">
        <div>
          <div className="teacher-page-title-line"><span className="teacher-page-title-icon"><Icon name="calendar" size={27} /></span><h1>Timetable</h1></div>
          <p>Scheduled examinations awaiting their start, organised by date and academic level.</p>
        </div>
        <div className="admin-timetable-actions"><AdminDatePicker label="Timetable date" value={selectedDay} onChange={setSelectedDay} /><button type="button" className="teacher-secondary-action" disabled={adminData.loading || refreshing} onClick={refresh}><Icon name="sync" size={16} />{refreshing ? 'Refreshing...' : 'Refresh'}</button></div>
      </header>

      {levelId ? <section className="admin-timetable-toolbar" aria-label="Selected schedule">
        <div className="admin-timetable-scope"><span className="admin-timetable-eyebrow">Level collection</span><h2>{levelName} schedule</h2><p>Scheduled papers and start times for this level.</p></div>
        <button type="button" className="teacher-secondary-action" onClick={() => onSelectLevel(null)}><Icon name="back" size={16} />All level schedules</button>
      </section> : <div className="admin-timetable-level-filter"><SelectControl label="Filter by academic level" value={levelFilter} options={[{ value: 'all', label: 'All levels' }, ...levels.map((level) => ({ value: level.id, label: level.name }))]} onChange={setLevelFilter} /></div>}

      {issue && <Notice tone="warning">{issue} The timetable may be incomplete or out of date.</Notice>}
      {!levelId && <section aria-label="Level schedules" aria-busy={adminData.loading || refreshing}>
        {adminData.loading && <p className="admin-timetable-summary" role="status">Loading timetable...</p>}
        {!adminData.loading && <div className="admin-timetable-collections">{visibleLevels.map((level) => {
          const exams = allScheduled.filter((exam) => exam.academicLevelId === level.id)
          return <button type="button" className="admin-timetable-collection" key={level.id} onClick={() => onSelectLevel(level.id)} aria-label={`Open ${level.name} schedule`}>
            <span className="admin-timetable-collection-icon" aria-hidden="true">
              <svg viewBox="0 0 160 144" fill="none">
                <rect x="20" y="26" width="124" height="112" rx="14" fill="currentColor" opacity=".07" />
                <rect x="12" y="18" width="124" height="112" rx="14" className="admin-timetable-calendar-paper" stroke="currentColor" strokeWidth="2" />
                <path d="M26 18h96a14 14 0 0 1 14 14v22H12V32a14 14 0 0 1 14-14Z" fill="currentColor" />
                <path d="M42 10v20M106 10v20" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
                {[32, 62, 92].map((x) => [70, 94].map((y) => <rect key={`${x}-${y}`} x={x} y={y} width="18" height="12" rx="3" fill="currentColor" opacity={x === 62 && y === 70 ? '.85' : '.14'} />))}
                <circle cx="124" cy="112" r="21" className="admin-timetable-calendar-paper" stroke="currentColor" strokeWidth="2" />
                <path d="M124 101v12l8 4" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <h3>{level.name} schedule</h3>
            <p>{exams.length} scheduled {exams.length === 1 ? 'exam' : 'exams'}</p>
            <span className="admin-timetable-collection-footer">View schedule<Icon name="chevronRight" size={17} /></span>
          </button>
        })}</div>}
        {!adminData.loading && (issue || !levels.length) && <div className="admin-timetable-empty"><h3>{issue ? 'Timetable unavailable' : 'No academic levels available'}</h3><p>{issue ? 'Refresh to try loading the schedule again.' : 'Level schedules will appear once the school curriculum is available.'}</p></div>}
      </section>}
      {levelId && <section className="admin-timetable-schedule" aria-label="Scheduled examinations" aria-busy={adminData.loading || refreshing}>
        <div className="admin-timetable-summary"><span role="status">{adminData.loading ? 'Loading timetable...' : `${scheduled.length} scheduled ${scheduled.length === 1 ? 'exam' : 'exams'} on ${dateFormat.format(new Date(`${selectedDay}T12:00:00`))}`}</span><span>Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}</span></div>
        {!adminData.loading && [...days].map(([day, group]) => (
          <section className="admin-timetable-day" key={day} aria-label={dateFormat.format(group.date)}>
            <header className="admin-timetable-day-heading"><span className="admin-timetable-date-tile" aria-hidden="true"><small>{group.date.toLocaleDateString(undefined, { month: 'short' })}</small><strong>{group.date.getDate()}</strong></span><div><h3>{dateFormat.format(group.date)}</h3><p>{group.exams.length} {group.exams.length === 1 ? 'examination' : 'examinations'}</p></div></header>
            <ol className="admin-timetable-list">
              {group.exams.map((exam) => (
                <li className="admin-timetable-row" key={exam.id}>
                  <div className="admin-timetable-time"><Icon name="clock" size={17} /><time dateTime={exam.scheduledStartAt}>{timeFormat.format(new Date(exam.scheduledStartAt))}</time></div>
                  <div className="admin-timetable-paper"><h4>{exam.title}</h4><p>{exam.subjectName} <span aria-hidden="true">·</span> {exam.assessmentName}</p></div>
                  <span className="admin-timetable-level">{exam.academicLevelName || 'Level unavailable'}</span>
                  <div className="admin-timetable-duration"><strong>{exam.durationMinutes} min</strong><small>Duration</small></div>
                  <span className="admin-timetable-status" data-status={exam.status}>{exam.statusLabel || exam.status}</span>
                </li>
              ))}
            </ol>
          </section>
        ))}
        {!adminData.loading && scheduled.length === 0 && <div className="admin-timetable-empty"><span><Icon name="calendar" size={32} /></span><h3>{issue ? 'Timetable unavailable' : 'No scheduled examinations'}</h3><p>{issue ? 'Refresh to try loading the schedule again.' : `There are no scheduled examinations for ${levelName} on ${dateFormat.format(new Date(`${selectedDay}T12:00:00`))}. Choose another date or level to view its timetable.`}</p></div>}
      </section>}
    </div>
  )
}
