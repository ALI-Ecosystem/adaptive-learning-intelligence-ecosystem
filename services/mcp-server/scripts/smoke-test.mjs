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
  for (const guidance of [/complete exact original user message/, /Do not paraphrase, summarize, translate/, /self-reports, not objectively verified knowledge/, /stronger evidence than self-reports/, /recommend 1-2 focused diagnostic practice questions/, /not automatically presented to the learner/]) {
    assert.match(init.result.instructions, guidance);
  }
  for (const field of ['topics.domain', 'topics.parent_topic', 'topics.concepts', 'knowledge_assessment[].concept', 'recommendations.topics[].concept', 'recommendations.practice_questions[].concept']) {
    assert.ok(init.result.instructions.includes(field), 'Naming guidance must cover ' + field);
  }
  assert.match(init.result.instructions, /Call whenActive also for ALI mode commands, mode-status inquiries/);
  assert.match(init.result.instructions, /new conversation defaults to OPEN/);
  assert.match(init.result.instructions, /use interaction.answer = null when no answer is available or permitted/);
  child.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
  const listed = (await request('tools/list')).result.tools;
  const simple = event('What is useEffect?');
  simple.interaction.answer = 'useEffect lets a component synchronize with an external system.';
  assert.equal(listed.length, 1);
  assert.equal(listed[0].name, 'whenActive');
  assert.deepEqual(Object.keys(listed[0].inputSchema.properties).sort(), Object.keys(simple).sort());
  const properties = listed[0].inputSchema.properties;
  for (const field of [properties.topics.properties.domain, properties.topics.properties.parent_topic, properties.topics.properties.concepts.items, properties.knowledge_assessment.items.properties.concept, properties.recommendations.properties.topics.items.properties.concept, properties.recommendations.properties.practice_questions.items.properties.concept]) {
    assert.equal(field.enum, undefined, 'Topic/concept names must remain free-form');
  }
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
  const selfReport = event('אני יודע לכוון גיטרה.');
  selfReport.learning_intent = 'בירור ידע מדווח בכיוון גיטרה.';
  selfReport.topics = { domain: 'Music', parent_topic: 'Guitar', concepts: ['Guitar Tuning'] };
  selfReport.observations = ['הלומד מדווח שהוא יודע לכוון גיטרה; לא נצפה ביצוע.'];
  selfReport.knowledge_assessment = [{ concept: 'Guitar Tuning', status: 'unknown', assessment: 'יכולת מדווחת עצמית שלא אומתה בביצוע.', evidence: selfReport.interaction.question, why: 'הצהרת יכולת אינה מדגימה את המיומנות.', confidence: 'medium' }];
  selfReport.recommendations = { topics: [{ concept: 'Guitar Tuning', action: 'verify', why: 'היכולת דווחה אך לא הודגמה.' }], practice_questions: [{ concept: 'Guitar Tuning', question: 'כיצד תבדוק שמיתר מכוון לצליל הרצוי?', purpose: 'בירור ההבנה שמאחורי היכולת המדווחת.', difficulty: 'basic' }] };
  const events = [simple, positive, misconception, correction, privateEvent, selfReport];
  const conversations = [
    ['What is Redis?', 'open_ended'],
    ['Is my understanding of useEffect correct?', 'true_false'],
    ['Kubernetes', 'other'],
    ['Write a React component', 'coding'],
  ];
  events.push(...conversations.map(([question]) => event(question)));
  // Preclassified fixtures check the contract round trip, not live AI classification.
  for (const [question, mode, question_format] of [
    ["  I'm practicing algorithms.\nI answered O(n) for Binary Search because I think it checks every element.\nIs that correct?  ", 'practice', 'open_ended'],
    ['Give me a multiple-choice question about HTTP status codes.', 'practice', 'multiple_choice'],
    ["Let's practice Python together.", 'practice', 'none'],
    ['This is question 3 of my assessment. I selected D. Evaluate my answer.', 'assessment', 'multiple_choice'],
    ['Start a five-question knowledge assessment without hints.', 'assessment', 'none'],
  ]) {
    events.push({ ...event(question), interaction_type: { mode, question_format } });
  }
  for (const mode of ['practice', 'assessment']) {
    const followUp = event('I selected D. Was that correct?');
    followUp.interaction_type = { mode, question_format: 'multiple_choice' };
    followUp.observations = [mode === 'practice'
      ? 'Earlier, the learner explicitly requested a practice exercise with feedback.'
      : 'Earlier, the learner explicitly started a structured knowledge assessment.'];
    events.push(followUp);
  }
  for (const mode of ['practice', 'assessment']) {
    for (const question_format of ['multiple_choice', 'true_false', 'open_ended', 'coding', 'other', 'none']) {
      events.push({ ...event('Synthetic exercise'), interaction_type: { mode, question_format } });
    }
  }
  const returned = [];
  // These assertions verify emitted policy, NOT AI decisions or chat state.
  const modeRules = [
    /default_mode: OPEN/, // New conversation.
    /OPEN:\nAnswer normally[\s\S]*?Do not apply material restrictions/, // No OPEN gate.
    /Enable materials-only learning => MATERIALS_ONLY/, // Explicit activation.
    /disable it or clearly request normal answers from now on => OPEN/, // Deactivation.
    /Status inquiries report the mode from conversation context without changing it/,
    /Ambiguous requests require a short clarification without changing the current mode/,
    /status: OUT_OF_SCOPE\napproved_material_available: false\nsimulation: true/,
    /YES: Do not repeat[\s\S]*?Permission applies to this request only; retain MATERIALS_ONLY/,
    /NO: Do not repeat[\s\S]*?Retain MATERIALS_ONLY/,
    /Treat these as permission only when context establishes a pending permission/,
    /Do not repeat it on later turns/, // One-time discovery guidance.
    /quoted command examples, discussion of commands and unrelated text do not/,
    /native question mechanism[\s\S]*?If the native mechanism is unavailable/,
    /No actual materials were searched, retrieved or verified/,
    /not guaranteed across external clients/,
  ];
  // Mode-control and permission messages still use the unmodified seven fields.
  events.push(...[
    'ALI הפעל מצב חומרי לימוד', 'ALI כבה מצב חומרי לימוד',
    'ALI מה המצב הנוכחי?', 'Maybe change the learning mode?',
    '1', '2', 'כן', 'לא',
    '<send_user_message_question_reply>\n' + JSON.stringify([{
      question: 'לא נמצא חומר לימוד מאושר בנושא הזה. האם תרצה להמשיך עם הסבר המבוסס על ידע כללי?',
      answer: 'כן, המשך עם ידע כללי',
    }]) + '\n</send_user_message_question_reply>',
  ].map(event));
  for (const input of events) {
    const reply = await request('tools/call', { name: 'whenActive', arguments: input });
    assert.ok(reply.result && !reply.result.isError, JSON.stringify(reply));
    assert.equal(reply.result.content.length, 2);
    const guidance = reply.result.content[1];
    assert.equal(guidance.type, 'text');
    for (const rule of modeRules) assert.match(guidance.text, rule);
    for (const text of ['לא נמצא חומר לימוד מאושר בנושא הזה. האם תרצה להמשיך עם הסבר המבוסס על ידע כללי?', 'כן, המשך עם ידע כללי', 'לא, הישאר במסגרת חומרי הלמידה', '"1", "כן", "yes"', '"2", "לא", "no"', 'send_user_message_question_reply']) {
      assert.ok(guidance.text.includes(text), 'Missing permission guidance: ' + text);
    }
    returned.push(JSON.parse(reply.result.content[0].text));
  }
  const invalid = [
    { ...simple, timestamp: 'invented' },
    { ...simple, interaction: { ...simple.interaction, answer_status: 'delivered' } },
    { ...simple, observations: [{ id: 'invented' }] },
    ...[...conversations, ['Which option would you recommend?', 'multiple_choice']].map(([question, question_format]) => ({ ...event(question), interaction_type: { mode: 'conversation', question_format } })),
  ];
  for (const input of invalid) {
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
  });
  // Short replies such as "1" can occur inside UUIDs; validate entire log lines.
  for (const line of stderr.trim().split(/\r?\n/).filter(Boolean)) {
    assert.match(line, /^\[whenActive\] Saved activation [0-9a-f-]{36}$/);
  }
  console.log('PASS: ' + events.length + ' MCP writes and ' + invalid.length + ' rejected inputs; purpose/context fixtures, conversation requires none, both exercise modes accept all six formats, seven-field contract and intended answers preserved. Live AI mode classification and opt-out activation require a live host test.');
  console.log('Example JSONL: ' + JSON.stringify(records[0]));
  console.log('PASS: conditional mode guidance, permission options/replies, context-only state and discovery rules advertised after logging; actual conversation-mode transitions and UI require manual Codex tests.');
} finally {
  const exited = child.exitCode === null && child.signalCode === null ? once(child, 'exit') : null;
  if (exited) { const timer = setTimeout(() => child.kill(), 2000); child.stdin.end(); try { await exited; } finally { clearTimeout(timer); } }
  lines.close();
  await unlink(logPath);
  await rmdir(directory);
}
