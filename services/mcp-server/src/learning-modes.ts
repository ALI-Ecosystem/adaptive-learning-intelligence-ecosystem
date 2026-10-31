// The stdio integration supplies no guaranteed chat-conversation identifier.
// These are agent instructions, not server-owned state or enforced permissions.
export const learningModeInstructions = `ALI supports optional conversation-scoped learning modes, distinct from interaction_type.mode. A new conversation defaults to OPEN. Use conversation context to remember explicit mode changes, pending permissions and whether the introduction was shown; this is best-effort, not server-enforced or durable state. Never invent a conversation ID or reuse another conversation's state.
Call whenActive also for ALI mode commands, mode-status inquiries, ambiguous mode requests and permission replies, at most once per user message, respecting privacy opt-outs. Read its result before responding. Apply the learning-mode rules before preparing an explanation; do not draft an answer while permission is pending. Keep the complete available intended-answer capture rule; use interaction.answer = null when no answer is available or permitted.
Learners can enable, disable or check the mode in Hebrew or English, for example: "ALI הפעל מצב חומרי לימוד", "ALI כבה מצב חומרי לימוד", "ALI מה המצב הנוכחי?", or "ALI תענה לי רגיל מעכשיו". Only clear explicit intent changes mode; quoted examples and unrelated text do not. Clarify ambiguous intent without changing mode. OPEN answers normally without material restrictions or permission questions. MATERIALS_ONLY asks permission for general knowledge when approved material is unavailable; currently unavailability is simulated, with no actual retrieval. Follow the conditional guidance in the tool result, including one-request permission scope.
Introduce the optional feature briefly once during the first relevant learning interaction, without interrupting the answer or asking a discovery question. Skip the generic introduction if the first interaction requests a mode change. Track introduction/control acknowledgement in this conversation's context; do not repeat discovery after either has occurred. Do not assume clients display these instructions or tool descriptions to users.`;

export const learningModeGuidance = `ALI conversation learning modes — conditional client guidance
state_tracking: conversation_context_best_effort
default_mode: OPEN
The server does not know the active chat mode. Resolve it from this conversation's earlier explicit learner choices, not transport/session identity, question format or topic. No persistent preferences are stored. Do not claim server-enforced mode changes. If needed context has been lost, acknowledge uncertainty instead of inventing remembered state.

MODE CONTROL (before handling a learning request):
Interpret explicit learner intent in Hebrew or English, not exact strings alone. Enable materials-only learning => MATERIALS_ONLY; disable it or clearly request normal answers from now on => OPEN. Status inquiries report the mode from conversation context without changing it. Only explicit intent changes mode: quoted command examples, discussion of commands and unrelated text do not. Ambiguous requests require a short clarification without changing the current mode. Confirm a change only after adopting it in this conversation's context. Preserve that mode across follow-ups; a new conversation starts OPEN. A control-only message needs a brief acknowledgement/status/clarification, not a learning-material permission question. If a clear command also includes a learning question, apply the new mode to that question.

DISCOVERY (best-effort once per conversation):
If neither the introduction nor a mode-control acknowledgement has already appeared, briefly include this on the first relevant learning interaction, without delaying the normal answer:
ALI מחובר לשיחה. אפשר להפעיל מצב למידה שמבוסס על חומרי הלימוד שלך באמצעות 'ALI הפעל מצב חומרי לימוד', או להמשיך במצב רגיל.
Do not repeat it on later turns or display a question merely for discovery. If the first interaction explicitly requests a mode change, handle it directly instead of giving the generic introduction.

OPEN:
Answer normally using available knowledge and tools. Do not apply material restrictions, OUT_OF_SCOPE or permission questions. Continue normal learning-event capture with no extra tool calls.

MATERIALS_ONLY — NEW LEARNING REQUEST:
For this implementation only, simulate this condition:
status: OUT_OF_SCOPE
approved_material_available: false
simulation: true
No actual materials were searched, retrieved or verified. Explain briefly that this is a simulation, not a search result. Before explaining the requested topic with general knowledge, use the client's existing native question mechanism (request_user_input_async or request_user_input, if available) to ask exactly:
לא נמצא חומר לימוד מאושר בנושא הזה. האם תרצה להמשיך עם הסבר המבוסס על ידע כללי?
Options:
1. כן, המשך עם ידע כללי
2. לא, הישאר במסגרת חומרי הלמידה
If the native mechanism is unavailable, ask the same ordinary chat question with the same options. Do not claim an interactive card was displayed unless it was. Do not use MCP Elicitation. Wait for the choice; do not explain the original topic before permission. Remember the original request and pending permission in conversation context, not invented identifiers.

MATERIALS_ONLY — REPLY TO THAT PENDING PERMISSION:
Recognize the interactive selection (including the answer inside a send_user_message_question_reply envelope) and typed equivalents: "1", "כן", "yes" or the YES label; "2", "לא", "no" or the NO label. Treat these as permission only when context establishes a pending permission for this request; an unrelated yes/no or quoted example grants nothing. Resolve other clear natural-language choices by intent; clarify ambiguous choices without granting permission.
YES: Do not repeat the permission question. Answer the ORIGINAL request from conversation context using general knowledge. Clearly state: ההסבר הבא מבוסס על ידע כללי, ולא על חומרי לימוד מאושרים של ALI. Permission applies to this request only; retain MATERIALS_ONLY for subsequent new learning requests, which need their own permission. Do not reinterpret YES as switching to OPEN.
NO: Do not repeat the permission question or explain the requested topic. Briefly acknowledge: בסדר, נשאר במסגרת חומרי הלמידה ולא אשתמש בידע כללי לבקשה הזו. Retain MATERIALS_ONLY. Do not reinterpret NO as disabling the mode.
After either choice, consider that pending question resolved. Preserve the original request across the choice turn; if it is unavailable, ask for it instead of guessing. Call whenActive at most once per user message, including replies, and never retry a successful call to advance this flow.

All mode decisions, natural-language interpretation, one-time discovery and UI behavior depend on the AI/client following this guidance. They are not guaranteed across external clients. Preserve privacy and the existing seven-field learning-evidence contract; do not put mode-state fields or invented IDs into the learning event.`;
