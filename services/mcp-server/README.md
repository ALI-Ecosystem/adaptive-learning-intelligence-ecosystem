# ALI MCP activation experiment

The MCP server lives permanently in `services/mcp-server/`, alongside ALI's
other independent services. Everything is in **one TypeScript source file**,
`src/index.ts`, using the official MCP SDK 2.4.0 and stdio. The only tool is
`whenActive`; no production learning functionality is implemented.

## Build and run

Requires Node.js 22+ and npm. From this directory:

```powershell
npm.cmd ci
npm.cmd run build
node dist/index.js
```

The server waits for MCP messages on stdin. Codex normally launches it itself.
Only protocol messages go to stdout; activation logs go to stderr.

## Connect Codex

The repo's `.codex/config.toml` registers `ali-mcp-experiment` with the local
Node executable and absolute path to `services/mcp-server/dist/index.js`.
Adjust those two paths on another machine. Unrelated configuration is unchanged.
Build, trust this project in Codex, and restart the extension or start a fresh
local Codex session.

From the repo root, `codex mcp get ali-mcp-experiment --json` checks configuration.
Use `/mcp` in the CLI or the IDE MCP panel to confirm `whenActive` is discovered.
See the [official Codex MCP configuration](https://developers.openai.com/codex/mcp).

## Logs and smoke check

`whenActive` requires `reason` and `trigger`, each a short non-sensitive string
(1-300 characters). Never pass secrets, personal details, verbatim messages,
conversation history, or private reasoning. Validation does not redact secrets.
Each successful call appends its actual UTC timestamp, unique invocation ID,
reason and trigger to this service's git-ignored `logs/activations.jsonl`.

Ask Codex to call `whenActive` with reason `Manual smoke check` and trigger
`manual-smoke`, then inspect from this directory:

```powershell
Get-Content logs/activations.jsonl -Tail 1
```

For isolated smoke tests, set `ALI_MCP_LOG_PATH` to a temporary file before the
host launches the server. Starting the server alone creates no activation.
The simplified server was built, discovered and called through the installed
Codex app-server; the resulting record was verified in temporary storage.
That explicit smoke check started no model turn.

## Activation experiment

The server instructions encourage at most one call for a user message containing
concrete learning evidence: an attempted answer or solution, an explanation of
understanding, a demonstrated mistake or misconception, or explicit feedback
about learning progress or difficulty. Greetings, thanks, questions, general
requests, and follow-ups without learning evidence do not qualify. The agent
assesses this evidence; the logging tool does not enforce that assessment.
After restarting Codex, send these individually, waiting for each response:

1. `[M1] Hello.`
2. `[M2] Explain a JavaScript closure in one sentence.`
3. `[M3] I think a closure keeps access to variables from its outer function after that function returns.`
4. `[M4] I calculated 7 times 8 as 54 by adding seven eight times.`
5. `[M5] Give a short example.`
6. `[M6] I still struggle to identify which variables a closure captures.`
7. `[M7] Thanks.`

Expect calls for M3, M4 and M6 only. Compare actual tool calls and new log records
against the seven sent messages, including whether each contains learning evidence.
Record misses, errors and duplicates. Exclude manual smoke calls and never fill
in missing activations yourself. Repeat in a fresh session if useful.

MCP cannot guarantee automatic or exactly-once activation, and invocation logs
alone cannot count missed messages. Automatic consistency remains unmeasured.
This experiment has no HTTP, authentication, database or deployment setup.
