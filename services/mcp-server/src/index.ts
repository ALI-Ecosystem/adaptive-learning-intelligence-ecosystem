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
        'Call whenActive at most once per user message whenever it may involve learning, knowledge, skills, or problem-solving in any domain. Include questions, explanations, generated work, single-topic prompts, corrections, practice, and related follow-ups. Prefer calling when uncertain. Skip unrelated small talk and respect privacy opt-outs. Never include secrets or private model reasoning. Capture relevant question and answer text only when available and permitted; use null for missing or withheld text and omit irrelevant sensitive details. When calling whenActive, provide the most complete intended answer available in interaction.answer, preserving explanations, examples, and important details. Do not intentionally summarize or shorten the answer. Never claim it is an exact delivered response. Model-reported answer text is not a verified delivered transcript. Keep observations factual and assessments separate. A question alone is not evidence of difficulty, and AI-generated work is not demonstrated learner understanding. Capture positive understanding, possible difficulties and uncertainty when supported. Keep assessment evidence and rationales concise, with individually judged confidence; possible causes are hypotheses, not verified facts. Use empty assessment/recommendation arrays or an empty recommendations object when evidence is insufficient. Topics are suggested groupings for later ALI matching. Recommendations are suggestions, not final diagnoses. Capture useful immediate evidence without deep longitudinal analysis or delaying every response. Never invent missing text, history, profile facts, infrastructure IDs, timestamps, application or model identity. Do not retry successful calls.',
    },
  );

  server.registerTool('whenActive', {
    description:
      'Capture relevant learning evidence across any domain using the seven-field contract: interaction, interaction_type, learning_intent, topics, observations, knowledge_assessment and recommendations. Keep factual observations separate from tentative assessments. Include only permitted available text; use null and empty arrays when information is unavailable or unsupported. When calling whenActive, provide the most complete intended answer available in interaction.answer, preserving explanations, examples, and important details. Do not intentionally summarize or shorten the answer. Never claim it is an exact delivered response. Respect privacy opt-outs. Do not include secrets or private model reasoning.',
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
