import * as z from 'zod/v4';

const text = z.string().trim().min(1).max(2000);
const capturedText = z.string().min(1).max(32000).nullable()
  .describe('Relevant model-reported text, not a verified transcript. Use null if unavailable or not permitted.');

export const learningEventSchema = z.strictObject({
  interaction: z.strictObject({
    question: capturedText.describe('Complete exact original user message, preserving wording, reasoning, examples, formatting and language. Do not paraphrase, summarize or translate. Use null if exact text is unavailable or not permitted.'),
    answer: capturedText,
  }),
  interaction_type: z.strictObject({
    mode: z.enum(['conversation', 'practice', 'assessment'])
      .describe('Purpose and context, including earlier messages: conversation for ordinary help, practice for explicit learning exercises with feedback, assessment for explicit structured evaluation. Format or a submitted answer alone does not determine mode; default to conversation without explicit exercise context.'),
    question_format: z.enum(['open_ended', 'multiple_choice', 'true_false', 'coding', 'other', 'none'])
      .describe('Practice or assessment exercise format. Always none for conversation.'),
  }).refine(({ mode, question_format }) => mode !== 'conversation' || question_format === 'none', {
    message: 'Conversation interactions require question_format none.',
    path: ['question_format'],
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
    assessment: text.describe('Distinguish demonstrated understanding from self-reported ability; explicitly qualify self-reports as unverified.'),
    evidence: text,
    why: text,
    possible_cause: text.optional(),
    confidence: z.enum(['low', 'medium', 'high'])
      .describe('Model confidence that available evidence supports this status and assessment; not learner confidence, mastery, difficulty severity or proof of a persistent gap. If no meaningful evidence supports an assessment, leave knowledge_assessment empty.'),
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
    })).max(20).optional()
      .describe('Recommend 1-2 focused diagnostic questions when supported by an observed possible gap, uncertainty or verification opportunity. Optional suggestions for later ALI engines, not automatically presented to the learner; do not invent gaps or fill without justification.'),
  }),
});
