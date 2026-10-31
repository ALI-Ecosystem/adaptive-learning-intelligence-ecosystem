import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, rmdir, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const directory = await mkdtemp(join(tmpdir(), 'ali-mcp-'));
const logPath = join(directory, 'events.jsonl');
const legacy = '{"tool":"whenActive","provenance":"ai_reported_unverified","reason":"Historical synthetic record"}\n';
await writeFile(logPath, legacy);
const child = spawn(process.execPath, ['dist/index.js'], {
  cwd: fileURLToPath(new URL('../', import.meta.url)),
  env: { ...process.env, ALI_MCP_LOG_PATH: logPath }, stdio: ['pipe', 'pipe', 'pipe'],
});
const pending = new Map();
let nextId = 0;
let stderr = '';
child.stderr.on('data', (chunk) => { stderr += chunk; });
const rejectPending = (error) => { for (const waiter of pending.values()) { clearTimeout(waiter.timer); waiter.reject(error); } pending.clear(); };
child.on('error', rejectPending);
child.on('exit', () => rejectPending(new Error('Server exited before replying.')));
const lines = createInterface({ input: child.stdout });
lines.on('line', (line) => {
  try {
    const response = JSON.parse(line);
    const waiter = pending.get(response.id);
    if (waiter) { clearTimeout(waiter.timer); pending.delete(response.id); waiter.resolve(response); }
  } catch (error) { rejectPending(error); }
});
const request = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error('Timed out: ' + method)); }, 5000);
  pending.set(id, { resolve, reject, timer });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
});
const event = (question) => ({
  interaction: { question, answer: null },
  interaction_type: { mode: 'conversation', question_format: 'none' },
  learning_intent: 'Clarify a programming concept.',
  topics: { domain: 'Software Engineering', parent_topic: 'React Hooks', concepts: ['useEffect'] },
  observations: [], knowledge_assessment: [], recommendations: {},
});
try {
  const init = await request('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'ali-smoke', version: '1.0.0' } });
  assert.ok(init.result);
  assert.match(init.result.instructions, /respect privacy opt-outs/);
  assert.match(init.result.instructions, /whenever it may involve learning/);
  child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
  const listed = (await request('tools/list')).result.tools;
  const simple = event('What is useEffect?');
  simple.interaction.answer = 'useEffect lets a component synchronize with an external system.';
  assert.equal(listed.length, 1);
  assert.equal(listed[0].name, 'whenActive');
  assert.deepEqual(Object.keys(listed[0].inputSchema.properties).sort(), Object.keys(simple).sort());
  const positive = event('useState stores state for a component.');
  positive.topics.concepts = ['useState'];
  positive.observations = ['The learner describes component state.'];
  positive.knowledge_assessment = [{ concept: 'useState', status: 'understanding', assessment: 'Basic state knowledge is expressed.', evidence: positive.interaction.question, why: 'The statement matches the basic role of useState.', confidence: 'medium' }];
  const misconception = event('I think useEffect always runs only once.');
  misconception.observations = ['The learner proposes that effects always run once.'];
  misconception.knowledge_assessment = [{ concept: 'Effect dependencies', status: 'possible_difficulty', assessment: 'May be conflating dependency-array cases.', evidence: misconception.interaction.question, why: 'Effect execution depends on the dependencies.', possible_cause: 'Possible overgeneralization from an empty dependency array.', confidence: 'medium' }];
  misconception.recommendations = { topics: [{ concept: 'Effect dependencies', action: 'strengthen', why: 'The stated rule may be overgeneralized.' }], practice_questions: [{ concept: 'Effect dependencies', question: 'When does an effect with [userId] execute?', purpose: 'Check dependency-change understanding.', difficulty: 'basic' }] };
  const correction = event('I first said effects always run once. After the hint, I see that changing userId can rerun an effect with [userId].');
  correction.interaction_type = { mode: 'practice', question_format: 'open_ended' };
  correction.observations = ['The learner corrects the earlier rule after a hint.'];
  correction.knowledge_assessment = [{ concept: 'Effect dependencies', status: 'understanding', assessment: 'The correction shows assisted understanding.', evidence: correction.interaction.question, why: 'The learner connects a dependency change to rerunning the effect; independent retention is untested.', confidence: 'medium' }];
  const privateEvent = event(null);
  privateEvent.learning_intent = 'Clarify a concept; interaction text withheld for privacy.';
  const events = [simple, positive, misconception, correction, privateEvent];
  const returned = [];
  for (const input of events) {
    const reply = await request('tools/call', { name: 'whenActive', arguments: input });
    assert.ok(reply.result && !reply.result.isError, JSON.stringify(reply));
    returned.push(JSON.parse(reply.result.content[0].text));
  }
  for (const input of [{ ...simple, timestamp: 'invented' }, { ...simple, interaction: { ...simple.interaction, answer_status: 'delivered' } }, { ...simple, observations: [{ id: 'invented' }] }]) {
    const reply = await request('tools/call', { name: 'whenActive', arguments: input });
    assert.ok(reply.error || reply.result?.isError);
  }
  const bytes = await readFile(logPath, 'utf8');
  assert.ok(bytes.startsWith(legacy));
  const records = bytes.trim().split('\n').slice(1).map((line) => JSON.parse(line));
  assert.equal(records.length, events.length);
  records.forEach((record, index) => {
    const { tool, invocationId, timestamp, ...input } = record;
    assert.equal(tool, 'whenActive');
    assert.match(invocationId, /^[0-9a-f-]{36}$/);
    assert.ok(Number.isFinite(Date.parse(timestamp)));
    assert.deepEqual(input, events[index]);
    assert.deepEqual(returned[index], { success: true, ...record });
    assert.ok(!events[index].interaction.question || !stderr.includes(events[index].interaction.question));
  });
  console.log('PASS: five representative MCP writes, exact seven-field contract, three invalid inputs, privacy-minimized text, historical append compatibility, and metadata-only stderr. Opt-out activation itself requires a live host test.');
  console.log('Example JSONL: ' + JSON.stringify(records[0]));
} finally {
  const exited = child.exitCode === null && child.signalCode === null ? once(child, 'exit') : null;
  if (exited) { const timer = setTimeout(() => child.kill(), 2000); child.stdin.end(); try { await exited; } finally { clearTimeout(timer); } }
  lines.close();
  await unlink(logPath);
  await rmdir(directory);
}
