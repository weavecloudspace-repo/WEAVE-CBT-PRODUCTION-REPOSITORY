import { describe, expect, it, vi } from 'vitest'

import { createQuestionAIController } from './questionAIController'

const OPERATION_ID = '00000000-0000-0000-0000-000000000111'
const OTHER_OPERATION_ID = '00000000-0000-0000-0000-000000000222'

function memoryDraftStore() {
  const rows = new Map()
  return {
    put: vi.fn(async (row) => {
      rows.set(row.draft_id, structuredClone(row))
      return row
    }),
    get: vi.fn(async (id) => rows.get(id)),
    delete: vi.fn(async (id) => rows.delete(id)),
    rows,
  }
}

function generatedResponse(operationId) {
  return {
    operation_id: operationId,
    questions: [
      {
        question_type: 'single_choice',
        prompt: 'Question?',
        instruction: null,
        image: null,
        options: [
          { text: 'A', image: null, is_correct: true },
          { text: 'B', image: null, is_correct: false },
        ],
      },
    ],
    repaired: false,
    charge: {
      reservation_id: '00000000-0000-0000-0000-000000000001',
      credits_charged: 1,
      credits_released: 0,
    },
  }
}

describe('question AI controller', () => {
  it('persists the operation before generation and retries with the same id', async () => {
    const store = memoryDraftStore()
    const questionsApi = {
      generateAIQuestionDrafts: vi
        .fn()
        .mockRejectedValueOnce(new Error('connection lost'))
        .mockImplementationOnce(async (_bankId, payload) => generatedResponse(payload.operation_id)),
    }
    const controller = createQuestionAIController({
      questionsApi,
      draftStore: store,
      createOperationId: () => OPERATION_ID,
    })

    await expect(
      controller.generate('bank-1', { generation_prompt: 'Cells', question_count: 1 }),
    ).rejects.toMatchObject({ operationId: OPERATION_ID })

    expect(store.rows.get(OPERATION_ID)).toMatchObject({
      status: 'generating',
      generation_operation_id: OPERATION_ID,
    })

    const recovered = await controller.retryGeneration(OPERATION_ID)
    expect(recovered.status).toBe('review')
    expect(questionsApi.generateAIQuestionDrafts).toHaveBeenCalledTimes(2)
    for (const call of questionsApi.generateAIQuestionDrafts.mock.calls) {
      expect(call[1].operation_id).toBe(OPERATION_ID)
    }
  })

  it('keeps the IndexedDB review draft when permanent save fails', async () => {
    const store = memoryDraftStore()
    await store.put({
      draft_id: OPERATION_ID,
      bank_id: 'bank-1',
      status: 'review',
      questions: generatedResponse(OPERATION_ID).questions,
    })
    const questionsApi = {
      saveAIQuestionDrafts: vi.fn(async () => {
        throw new Error('network lost')
      }),
    }
    const controller = createQuestionAIController({ questionsApi, draftStore: store })

    await expect(controller.save(OPERATION_ID)).rejects.toThrow('network lost')
    expect(store.rows.has(OPERATION_ID)).toBe(true)
  })

  it('persists reviewed edits before save so a lost response can replay exactly', async () => {
    const store = memoryDraftStore()
    await store.put({
      draft_id: OPERATION_ID,
      bank_id: 'bank-1',
      status: 'review',
      questions: generatedResponse(OPERATION_ID).questions,
    })
    const editedQuestions = [
      {
        ...generatedResponse(OPERATION_ID).questions[0],
        prompt: 'Edited question?',
      },
    ]
    const questionsApi = {
      saveAIQuestionDrafts: vi.fn(async () => {
        throw new Error('response lost')
      }),
    }
    const controller = createQuestionAIController({ questionsApi, draftStore: store })

    await expect(controller.save(OPERATION_ID, editedQuestions)).rejects.toThrow('response lost')
    expect(store.rows.get(OPERATION_ID).questions).toEqual(editedQuestions)
    expect(questionsApi.saveAIQuestionDrafts).toHaveBeenCalledWith('bank-1', {
      draft_id: OPERATION_ID,
      questions: editedQuestions,
    })
  })

  it('clears the IndexedDB draft only after CBT confirms persistence', async () => {
    const store = memoryDraftStore()
    await store.put({
      draft_id: OPERATION_ID,
      bank_id: 'bank-1',
      status: 'review',
      questions: generatedResponse(OPERATION_ID).questions,
    })
    const questionsApi = {
      saveAIQuestionDrafts: vi.fn(async () => ({
        draft_id: OPERATION_ID,
        questions: [],
      })),
    }
    const controller = createQuestionAIController({ questionsApi, draftStore: store })

    await controller.save(OPERATION_ID)
    expect(store.rows.has(OPERATION_ID)).toBe(false)
  })

  it('preserves a failed regeneration operation so it can reuse the same id', async () => {
    const store = memoryDraftStore()
    await store.put({
      draft_id: OPERATION_ID,
      bank_id: 'bank-1',
      status: 'review',
      questions: generatedResponse(OPERATION_ID).questions,
      regeneration_charges: [],
    })
    const questionsApi = {
      regenerateAIQuestionDraft: vi
        .fn()
        .mockRejectedValueOnce(new Error('timeout'))
        .mockResolvedValueOnce({
          operation_id: OTHER_OPERATION_ID,
          question: {
            ...generatedResponse(OPERATION_ID).questions[0],
            prompt: 'Regenerated?',
          },
          repaired: false,
          charge: generatedResponse(OPERATION_ID).charge,
        }),
    }
    const controller = createQuestionAIController({
      questionsApi,
      draftStore: store,
      createOperationId: () => OTHER_OPERATION_ID,
    })

    await expect(
      controller.regenerateDraft(OPERATION_ID, 0, { instruction: 'Make it harder' }),
    ).rejects.toMatchObject({ operationId: OTHER_OPERATION_ID })

    expect(store.rows.get(OPERATION_ID).pending_regeneration.operation_id).toBe(OTHER_OPERATION_ID)
    const recovered = await controller.retryDraftRegeneration(OPERATION_ID)
    expect(recovered.questions[0].prompt).toBe('Regenerated?')
    expect(questionsApi.regenerateAIQuestionDraft).toHaveBeenCalledTimes(2)
    for (const call of questionsApi.regenerateAIQuestionDraft.mock.calls) {
      expect(call[1].operation_id).toBe(OTHER_OPERATION_ID)
    }
  })
})
