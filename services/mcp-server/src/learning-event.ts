import * as z from 'zod/v4';

const text = z.string().trim().min(1).max(2000);
const capturedText = z.string().min(1).max(32000).nullable()
  .describe('Relevant model-reported text, not a verified transcript. Use null if unavailable or not permitted.');

export const learningEventSchema = z.strictObject({
  interaction: z.strictObject({
    question: capturedText,
    answer: capturedText,
  }),
  interaction_type: z.strictObject({
    mode: z.enum(['conversation', 'practice', 'assessment']),
    question_format: z.enum(['open_ended', 'multiple_choice', 'true_false', 'coding', 'other', 'none']),
  }),
  learning_intent: text,
  topics: z.strictObject({
    domain: text.nullable(),
    parent_topic: text.nullable(),
    concepts: z.array(text).max(30),
  }),
  observations: z.array(text).max(30),
  knowledge_assessment: z.array(z.strictObject({
    concept: text,
    status: z.enum(['understanding', 'possible_difficulty', 'unknown']),
    assessment: text,
    evidence: text,
    why: text,
    possible_cause: text.optional(),
    confidence: z.enum(['low', 'medium', 'high']),
  })).max(30),
  recommendations: z.strictObject({
    topics: z.array(z.strictObject({
      concept: text,
      action: z.enum(['strengthen', 'expand', 'verify']),
      why: text,
    })).max(30).optional(),
    practice_questions: z.array(z.strictObject({
      concept: text,
      question: text,
      purpose: text,
      difficulty: z.enum(['basic', 'intermediate', 'advanced']),
    })).max(20).optional(),
  }),
});
