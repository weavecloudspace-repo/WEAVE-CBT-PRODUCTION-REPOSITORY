import { Icon } from '../icons/Icon'
import { SelectControl } from '../ui'
import { examStatuses } from './examPermissions'

export function ExamLifecycleFilter({ value, counts, onChange }) {
  return <div className="exam-lifecycle-filter">
    <span className="exam-lifecycle-filter__icon"><Icon name="filter" size={17} /></span>
    <SelectControl label="Lifecycle filter" value={value} onChange={onChange} options={examStatuses.map((status) => ({
      value: status,
      label: status === 'all' ? 'All statuses' : status.charAt(0).toUpperCase() + status.slice(1),
      description: `${counts[status] || 0} examinations`,
    }))} />
  </div>
}
