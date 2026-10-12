import * as academics from '../api/academics'
import * as ai from '../api/ai'
import * as branding from '../api/branding'
import * as candidates from '../api/candidates'
import * as exams from '../api/exams'
import * as installation from '../api/installation'
import * as makeups from '../api/makeups'
import * as media from '../api/media'
import * as questions from '../api/questions'
import * as results from '../api/results'
import * as staffAttempts from '../api/staffAttempts'
import * as staffAuth from '../api/staffAuth'
import * as sync from '../api/sync'
import * as timetable from '../api/timetable'

export const staffGateway = {
  ai,
  installation,
  branding,
  auth: staffAuth,
  academics,
  attempts: staffAttempts,
  candidates,
  exams,
  makeups,
  media,
  questions,
  results,
  sync,
  timetable,
}
