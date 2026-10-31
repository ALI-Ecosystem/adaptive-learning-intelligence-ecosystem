import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { randomUUID } from 'node:crypto';
import { appendFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { learningEventSchema } from './learning-event.js';

const logPath = process.env.ALI_MCP_LOG_PATH
  ? resolve(process.env.ALI_MCP_LOG_PATH)
  : fileURLToPath(new URL('../logs/activations.jsonl', import.meta.url));

serveStdio(() => {
  const server = new McpServer(
    { name: 'ali-mcp-experiment', version: '0.1.0' },
    {
      instructions:
        'Call whenActive at most once per user message whenever it may involve learning, knowledge, skills, or problem-solving in any domain. Include questions, explanations, generated work, single-topic prompts, corrections, practice, and related follow-ups. Prefer calling when uncertain. Skip unrelated small talk and respect privacy opt-outs. Never include secrets or private model reasoning. Capture text only when available and permitted; use null for missing or withheld text and omit irrelevant sensitive details. Preserve the complete exact original user message in interaction.question when available and permitted, including wording, uncertainty, reasoning, examples, structure, formatting and language. Do not paraphrase, summarize, translate or replace it with only the main question. Use null if exact text is unavailable or cannot be retained under privacy rules; never fabricate a verbatim transcript.  When calling whenActive, provide the most complete intended answer available in interaction.answer, preserving explanations, examples, and important details. Do not intentionally summarize or shorten the answer. Never claim it is an exact delivered response. Model-reported answer text is not a verified delivered transcript. Classify mode by purpose and context, including relevant earlier messages, not question format or whether an answer was submitted. Use conversation for ordinary explanations, conceptual understanding checks, code requests, examples or technical help without explicit exercise context. Use practice for explicit learning exercises intended to improve understanding through practice and feedback. Use assessment for explicit structured knowledge evaluations, tests, examinations or diagnostic assessments. Multiple-choice format or a submitted answer alone does not imply assessment; asking whether one is correct alone does not imply practice. Without explicit practice or assessment context, prefer conversation. For interaction_type, conversation always uses question_format none, including ordinary yes/no questions and programming requests. In practice or assessment, question_format describes the actual exercise format; use none when unknown or not applicable. Keep observations factual and assessments separate. A question alone is not evidence of difficulty, and AI-generated work is not demonstrated learner understanding. Capture positive understanding, possible difficulties and uncertainty when supported. Record claimed abilities in observations as self-reports, not objectively verified knowledge. If assessed, explicitly qualify self-reported or unverified ability using assessment, evidence, why and confidence. Demonstrated explanations, solutions or observable performance generally provide stronger evidence than self-reports.  Keep assessment evidence and rationales concise; possible causes are hypotheses, not verified facts. In knowledge_assessment, confidence is the model\'s confidence that available evidence supports its assigned status and assessment, not the learner\'s confidence, overall mastery, difficulty severity, or proof of a persistent or permanent gap. Use high for strong direct evidence, medium for partially correct or ambiguous evidence, and low for weak or indirect evidence. If no meaningful evidence supports understanding or difficulty, leave knowledge_assessment empty. Use empty assessment/recommendation arrays or an empty recommendations object when evidence is insufficient. Prefer English names for topics.domain, topics.parent_topic, topics.concepts, knowledge_assessment[].concept, recommendations.topics[].concept and recommendations.practice_questions[].concept. Preserve official technical terminology. Preserve the user\'s original language in conversational content, observations, assessments, explanations and evidence. This is a language preference, not a fixed taxonomy; ALI will normalize concepts later. Topics are suggested groupings for later ALI matching. When evidence suggests a possible gap, uncertainty or an opportunity to verify understanding, proactively recommend 1-2 focused diagnostic practice questions targeting identified concepts, with concept, question, purpose and difficulty. Do not invent gaps or generate questions merely to fill the field. Recommendations are not automatically presented to the learner; the Diagnosis Engine and Adaptive Learning Engine decide which interventions to use. Recommendations are suggestions, not final diagnoses. Capture useful immediate evidence without deep longitudinal analysis or delaying every response. Never invent missing text, history, profile facts, infrastructure IDs, timestamps, application or model identity. Do not retry successful calls.',
    },
  );

  server.registerTool('whenActive', {
    description:
      'Capture relevant learning evidence across any domain using the seven-field contract: interaction, interaction_type, learning_intent, topics, observations, knowledge_assessment and recommendations. Classify mode by purpose and context, including relevant earlier messages, not question format or whether an answer was submitted. Use conversation for ordinary explanations, conceptual understanding checks, code requests, examples or technical help without explicit exercise context. Use practice for explicit learning exercises intended to improve understanding through practice and feedback. Use assessment for explicit structured knowledge evaluations, tests, examinations or diagnostic assessments. Multiple-choice format or a submitted answer alone does not imply assessment; asking whether one is correct alone does not imply practice. Without explicit practice or assessment context, prefer conversation. For interaction_type, conversation always uses question_format none, including ordinary yes/no questions and programming requests. In practice or assessment, question_format describes the actual exercise format; use none when unknown or not applicable. Prefer English names for topics.domain, topics.parent_topic, topics.concepts, knowledge_assessment[].concept, recommendations.topics[].concept and recommendations.practice_questions[].concept. Preserve official technical terminology. Preserve the user\'s original language in conversational content, observations, assessments, explanations and evidence. This is a language preference, not a fixed taxonomy; ALI will normalize concepts later. Keep factual observations separate from tentative assessments. Include only permitted available text; use null and empty arrays when information is unavailable or unsupported. Preserve the complete exact original user message in interaction.question when available and permitted, including wording, uncertainty, reasoning, examples, structure, formatting and language. Do not paraphrase, summarize, translate or replace it with only the main question. Use null if exact text is unavailable or cannot be retained under privacy rules; never fabricate a verbatim transcript. Record claimed abilities in observations as self-reports, not objectively verified knowledge. If assessed, explicitly qualify self-reported or unverified ability using assessment, evidence, why and confidence. Demonstrated explanations, solutions or observable performance generally provide stronger evidence than self-reports. When evidence suggests a possible gap, uncertainty or an opportunity to verify understanding, proactively recommend 1-2 focused diagnostic practice questions targeting identified concepts, with concept, question, purpose and difficulty. Do not invent gaps or generate questions merely to fill the field. Recommendations are not automatically presented to the learner; the Diagnosis Engine and Adaptive Learning Engine decide which interventions to use.  When calling whenActive, provide the most complete intended answer available in interaction.answer, preserving explanations, examples, and important details. Do not intentionally summarize or shorten the answer. Never claim it is an exact delivered response. Respect privacy opt-outs. Do not include secrets or private model reasoning.',
    inputSchema: learningEventSchema,
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
  }, async (input) => {
    const record = {
      tool: 'whenActive',
      invocationId: randomUUID(),
      timestamp: new Date().toISOString(),
      ...input,
    };
    try {
      await mkdir(dirname(logPath), { recursive: true });
      await appendFile(logPath, JSON.stringify(record) + '\n', { encoding: 'utf8', mode: 0o600 });
      process.stderr.write('[whenActive] Saved activation ' + record.invocationId + '\n');
      return { content: [{ type: 'text' as const, text: JSON.stringify({ success: true, ...record }) }] };
    } catch {
      process.stderr.write('[whenActive] Could not persist activation.\n');
      return { isError: true, content: [{ type: 'text' as const, text: 'Could not persist activation.' }] };
    }
  });

  return server;
});
