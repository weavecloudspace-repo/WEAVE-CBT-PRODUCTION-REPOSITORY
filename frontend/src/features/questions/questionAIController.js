import { staffGateway } from '../../app/staffGateway'

const DB_NAME = 'weave-cbt-ai-question-drafts'
const DB_VERSION = 1
const STORE_NAME = 'drafts'

function openDraftDatabase(indexedDBImpl = globalThis.indexedDB, scope = '') {
  if (!indexedDBImpl) throw new Error('IndexedDB is unavailable in this browser.')
  return new Promise((resolve, reject) => {
    const request = indexedDBImpl.open(scope ? `${DB_NAME}:${scope}` : DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'draft_id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Unable to open AI draft storage.'))
  })
}

function transact(database, mode, action) {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, mode)
    const store = transaction.objectStore(STORE_NAME)
    let request
    try {
      request = action(store)
    } catch (error) {
      reject(error)
      return
    }
    if (request) {
      transaction.oncomplete = () => resolve(request.result)
      request.onerror = () => reject(request.error || new Error('AI draft storage operation failed.'))
    } else {
      transaction.oncomplete = () => resolve(undefined)
    }
    transaction.onabort = () => reject(transaction.error || new Error('AI draft storage transaction was aborted.'))
    transaction.onerror = () => reject(transaction.error || new Error('AI draft storage transaction failed.'))
  })
}

export function createQuestionAIDraftStore({ indexedDBImpl = globalThis.indexedDB, scope = '' } = {}) {
  return {
    async list() {
      const database = await openDraftDatabase(indexedDBImpl, scope)
      try {
        return await transact(database, 'readonly', (store) => store.getAll())
      } finally {
        database.close()
      }
    },
    async put(draft) {
      const database = await openDraftDatabase(indexedDBImpl, scope)
      try {
        await transact(database, 'readwrite', (store) => store.put(draft))
      } finally {
        database.close()
      }
      return draft
    },
    async get(draftId) {
      const database = await openDraftDatabase(indexedDBImpl, scope)
      try {
        return await transact(database, 'readonly', (store) => store.get(draftId))
      } finally {
        database.close()
      }
    },
    async delete(draftId) {
      const database = await openDraftDatabase(indexedDBImpl, scope)
      try {
        await transact(database, 'readwrite', (store) => store.delete(draftId))
      } finally {
        database.close()
      }
    },
  }
}

function defaultOperationId() {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error('Secure browser UUID generation is unavailable.')
  }
  return globalThis.crypto.randomUUID()
}

function tagOperationError(error, operationId) {
  if (error && typeof error === 'object') error.operationId = operationId
  return error
}

export function createQuestionAIController({
  questionsApi = staffGateway.questions,
  draftStore = createQuestionAIDraftStore(),
  createOperationId = defaultOperationId,
} = {}) {
  async function generate(bankId, input, { operationId } = {}) {
    const operation_id = operationId || createOperationId()
    const pending = {
      draft_id: operation_id,
      bank_id: bankId,
      status: 'generating',
      generation_operation_id: operation_id,
      generation_request: input,
      questions: [],
      regeneration_charges: [],
      updated_at: new Date().toISOString(),
    }
    // Persist the operation identity before the HTTP call. If the browser loses
    // the response or refreshes, retryGeneration can safely reuse the same ID.
    await draftStore.put(pending)

    let response
    try {
      response = await questionsApi.generateAIQuestionDrafts(bankId, {
        ...input,
        operation_id,
      })
    } catch (error) {
      throw tagOperationError(error, operation_id)
    }

    const draft = {
      ...pending,
      status: 'review',
      generation_operation_id: response.operation_id,
      questions: response.questions,
      repaired: response.repaired,
      generation_charge: response.charge,
      updated_at: new Date().toISOString(),
    }
    try { await draftStore.put(draft) } catch (error) { throw tagOperationError(error, operation_id) }
    return draft
  }

  async function retryGeneration(operationId) {
    const pending = await draftStore.get(operationId)
    if (!pending || pending.status !== 'generating') {
      throw new Error('Pending AI generation operation was not found.')
    }
    return generate(
      pending.bank_id,
      pending.generation_request,
      { operationId },
    )
  }

  async function updateDraftQuestions(draftId, questions) {
    const draft = await draftStore.get(draftId)
    if (!draft || draft.status !== 'review') {
      throw new Error('AI question draft was not found.')
    }
    if (draft.pending_regeneration) throw new Error('Resolve the pending regeneration before editing this draft.')
    const updated = {
      ...draft,
      questions,
      updated_at: new Date().toISOString(),
    }
    await draftStore.put(updated)
    return updated
  }

  async function regenerateDraft(
    draftId,
    questionIndex,
    input,
    { operationId } = {},
  ) {
    const draft = await draftStore.get(draftId)
    if (!draft || draft.status !== 'review') {
      throw new Error('AI question draft was not found.')
    }
    if (draft.pending_regeneration && draft.pending_regeneration.operation_id !== operationId) {
      throw new Error('Retry the pending regeneration before starting another.')
    }
    const existingQuestion = draft.questions?.[questionIndex]
    if (!existingQuestion) throw new Error('AI question draft item was not found.')

    const operation_id = operationId || createOperationId()
    const pendingDraft = {
      ...draft,
      pending_regeneration: {
        operation_id,
        question_index: questionIndex,
        input,
      },
      updated_at: new Date().toISOString(),
    }
    await draftStore.put(pendingDraft)

    let response
    try {
      response = await questionsApi.regenerateAIQuestionDraft(draft.bank_id, {
        ...input,
        operation_id,
        existing_question: existingQuestion,
      })
    } catch (error) {
      throw tagOperationError(error, operation_id)
    }

    const questions = [...draft.questions]
    questions[questionIndex] = response.question
    const updated = {
      ...pendingDraft,
      questions,
      pending_regeneration: null,
      regeneration_charges: [
        ...(draft.regeneration_charges || []),
        { operation_id: response.operation_id, charge: response.charge },
      ],
      updated_at: new Date().toISOString(),
    }
    await draftStore.put(updated)
    return updated
  }

  async function retryDraftRegeneration(draftId) {
    const draft = await draftStore.get(draftId)
    const pending = draft?.pending_regeneration
    if (!draft || !pending) {
      throw new Error('Pending AI regeneration operation was not found.')
    }
    return regenerateDraft(
      draftId,
      pending.question_index,
      pending.input,
      { operationId: pending.operation_id },
    )
  }

  async function regenerateStored(questionId, input, { operationId } = {}) {
    const operation_id = operationId || createOperationId()
    try {
      return await questionsApi.regenerateStoredQuestionWithAI(questionId, {
        ...input,
        operation_id,
      })
    } catch (error) {
      throw tagOperationError(error, operation_id)
    }
  }

  async function save(draftId, questions = null) {
    let draft = await draftStore.get(draftId)
    if (!draft || !['review', 'saving'].includes(draft.status)) {
      throw new Error('AI question draft was not found.')
    }
    if (draft.pending_regeneration) throw new Error('Resolve the pending regeneration before adding questions.')
    if (questions !== null) {
      draft = await updateDraftQuestions(draftId, questions)
    }

    // Freeze the exact payload before sending: a lost response must replay it unchanged.
    draft = { ...draft, status: 'saving' }
    await draftStore.put(draft)
    let result
    try {
      result = await questionsApi.saveAIQuestionDrafts(draft.bank_id, {
        draft_id: draft.draft_id,
        questions: draft.questions,
      })
    } catch (error) {
      // Schema rejection happens before persistence, so these drafts remain editable.
      if (error.status === 422) await draftStore.put({ ...draft, status: 'review' })
      throw error
    }
    // Keep the IndexedDB copy through every failure path. The CBT backend makes
    // draft_id persistence idempotent, so even a lost success response is safe
    // to retry. Clear browser state only after a confirmed/replayed success.
    // Cleanup must not turn a confirmed server save into a reported failure.
    try { await draftStore.delete(draftId) } catch { /* A replay remains idempotent. */ }
    return result
  }

  return {
    generate,
    retryGeneration,
    updateDraftQuestions,
    regenerateDraft,
    retryDraftRegeneration,
    regenerateStored,
    listDrafts: () => draftStore.list(),
    getDraft: (draftId) => draftStore.get(draftId),
    discardDraft: (draftId) => draftStore.delete(draftId),
    save,
  }
}
