# ADR 112: Profile Agent chat uses an industry UI resource

## Status

Accepted

## Context

The Profile detail page needs a real conversation surface: streaming assistant
messages, thread state, Markdown, error handling, and mobile-friendly composer
behavior. The Manager already owns the authenticated Profile Agent app-server
bridge and its SSE event stream. Rebuilding those interaction patterns as a
local set of bubbles and a textarea would duplicate a mature UI problem.

The repository is a dependency-free vanilla-JavaScript shell rather than a
React application. The existing server-side Agent boundary also chooses the
provider and keeps credentials out of the browser. The chat UI must therefore
remain provider-neutral even though the selected reusable web resource is
published by OpenAI.

## Decision

Use the official ChatKit Web Component as the Profile Agent chat surface:

- [ChatKit JS](https://openai.github.io/chatkit-js/)
- [ChatKit JS quickstart](https://openai.github.io/chatkit-js/quickstart/)
- [ChatKit Python protocol types](https://github.com/openai/chatkit-python/blob/main/chatkit/types.py)

Load the component lazily only when the Profile Agent session tab is opened.
`profile/chatkit-adapter.js` translates ChatKit's thread and streaming event
protocol to the existing authenticated Manager RPC/SSE bridge. It does not
select a model provider, receive a provider token, or expose a server-local
path. Provider selection remains a server/Profile concern, so future
non-OpenAI providers can use the same UI protocol adapter.

The following alternatives were reviewed against the current shell and the
future multi-provider requirement:

- [assistant-ui](https://www.assistant-ui.com/docs/) has the broadest reusable
  React surface and explicitly supports custom runtimes, REST/custom protocols,
  AG-UI, A2A, LangGraph, Google ADK and other backends. Its
  [custom runtime](https://www.assistant-ui.com/docs/runtimes/custom/overview)
  is the strongest future migration candidate, but it requires a React build.
- [Vercel AI Elements](https://elements.ai-sdk.dev/) provides composable
  conversation, prompt, tool, source and workflow components. It is source
  code installed into a React/shadcn application and is closely integrated with
  the Vercel AI SDK, so it is not a drop-in dependency for this vanilla shell.
- [CopilotKit](https://docs.copilotkit.ai/) provides ready-made React chat
  components and a headless UI, while its runtime accepts any
  [AG-UI-compatible backend](https://docs.ag-ui.com/). It is a good option if
  FactorTester later adopts AG-UI for tool calls and generative UI, but it also
  introduces a React runtime and a larger agent-UI integration surface.
- [Flowise Embed](https://docs.flowiseai.com/using-flowise/embed) is the closest
  script-level embed and supports a maintained web widget, but it couples the
  UI to a Flowise chatflow/backend rather than to FactorTester's authenticated
  Profile Agent protocol.

The current Manager remains a dependency-free vanilla shell. Therefore the
selected ChatKit Web Component is only the presentation layer; the local
`chatkit-adapter.js` and `chatkit-protocol.js` are provider-neutral. The
Profile Agent server may route to OpenAI, Anthropic, Google, local models, or a
future model gateway without exposing provider credentials or changing this
page. If the shell later migrates to React, assistant-ui is the preferred
replacement candidate, with AG-UI as the backend protocol boundary.

## Consequences

- The Profile page gains a maintained conversation UI instead of a custom
  transcript/composer implementation.
- The Manager must allow the official ChatKit script and iframe origin in the
  authenticated shell CSP.
- ChatKit itself is an external lazy-loaded dependency; a future offline or
  supply-chain requirement should vendor a pinned release and retain the same
  adapter boundary.
- Attachments and provider-specific widgets stay disabled until the Manager
  exposes corresponding authenticated protocol operations.
