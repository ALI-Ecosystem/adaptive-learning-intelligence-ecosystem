import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';
import { randomUUID } from 'node:crypto';
import { appendFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Keep smoke-test records separate; the default is relative to this service.
const logPath = process.env.ALI_MCP_LOG_PATH
  ? resolve(process.env.ALI_MCP_LOG_PATH)
  : fileURLToPath(new URL('../logs/activations.jsonl', import.meta.url));

serveStdio(() => {
  const server = new McpServer(
    { name: 'ali-mcp-experiment', version: '0.1.0' },
    {
      instructions:
        'Call whenActive at most once per user message whenever it may involve learning, knowledge, skills, or problem-solving in any domain. Include questions, explanations, generated work, single-topic prompts, corrections, and related follow-ups. Prefer calling when uncertain. Skip unrelated small talk and respect privacy opt-outs. Provide a brief, non-sensitive reason and trigger. Never include secrets, verbatim messages, or private reasoning. Do not retry successful calls.',
    },
  );

  server.registerTool(
    'whenActive',
    {
      description:
        'Record one activation in a local JSONL file only when the current user message contains concrete learning evidence, such as an attempted solution, demonstrated understanding or misconception, or explicit feedback about learning progress or difficulty. Questions and requests alone do not qualify. Use brief, non-sensitive summaries.',
      inputSchema: z.strictObject({
        reason: z.string().trim().min(1).max(300),
        trigger: z.string().trim().min(1).max(300),
      }),
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async ({ reason, trigger }) => {
      const record = {
        tool: 'whenActive',
        invocationId: randomUUID(),
        timestamp: new Date().toISOString(),
        reason,
        trigger,
      };
      try {
        await mkdir(dirname(logPath), { recursive: true });
        await appendFile(logPath, JSON.stringify(record) + '\n', {
          encoding: 'utf8',
          mode: 0o600,
        });
        process.stderr.write(`[whenActive] ${JSON.stringify(record)}\n`);
        return {
          content: [
            {
              type: 'text' as const,
              text: JSON.stringify({ success: true, ...record }),
            },
          ],
        };
      } catch {
        process.stderr.write('[whenActive] Could not persist activation.\n');
        return {
          isError: true,
          content: [
            { type: 'text' as const, text: 'Could not persist activation.' },
          ],
        };
      }
    },
  );

  return server;
});
