# Foundry Field Notes

Engineering notes from building the triage wedge on monō foundry — the
contract quirks worth knowing before the next server, the dependency and
workspace-collision costs that don't show up until you look, and why a
research pack about monō's own documentation ships inside this repository.
Written for whoever picks up the next Foundry-native piece of work here,
including future me.

Everything below is validated against the documented monō foundry contract
at the pinned commit referenced in the workspace's own `MONOFOUNDRY.md`, and
against the base Model Context Protocol specification at its own pinned
commit. Neither this document nor any artifact it describes was checked
against a live monō foundry session — no such session was available while
building this.

## The contract traps that don't announce themselves

**A `url` or `serverUrl` key in `.mcp.json` silently flips the transport.**
The workspace registration format looks like plain config:

```json
{
  "servers": {
    "triage": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_server"]
    }
  }
}
```

Foundry's own docs are explicit that adding either key — even innocuously,
even just to leave a comment-by-example for the next person — reclassifies
the entry as an SSE server instead of stdio, with no error and no warning.
For a server that only ever speaks stdio, the failure mode is not "SSE
doesn't work," it's "the server silently stops being launched the way you
think it is." Worth a structural check if you're ever asserting artifact
shape in a test: don't just check `command`/`args` are present, check `url`
and `serverUrl` are *absent*.

**The tool surface is declared once, at server start.** Foundry caches the
tool list per session. A server that wants to add or remove a tool needs a
new session to pick it up — there is no live re-registration path. This
shaped a real decision here: the triage server exposes exactly three tools
(`list_stuck_orders`, `get_order_triage_context`, `get_carrier_stats`) and
no more, because "add a fourth tool later" is a workspace restart, not a hot
patch.

**Every tool call has to land comfortably inside 30 seconds.** That's the
whole per-call budget, not a soft target. It's part of why the triage
server never calls out to Claude itself — every call it serves is a direct,
bounded HTTP round-trip against the existing OMS/WMS/TMS services, nothing
agentic in the loop.

**Skill descriptions carry a standing token cost.** A skill's frontmatter
`description` is read on every turn a workspace session considers whether
to trigger it — not just when the skill actually fires. That's a real
incentive to keep it terse, the same discipline a well-tuned system prompt
already needs, but easy to forget when a skill's procedure genuinely has
five steps worth documenting in the body.

**Discovery order matters, and workspace wins.** `.monofoundry/skills/<name>/SKILL.md`
is the first path a Foundry session scans, ahead of anything at the user's
home directory — so a workspace-local skill always shadows a personal one
with the same name. Convenient here (the triage skill is meant to be
workspace-scoped, not personal), worth knowing the day it isn't.

## The protocol layer underneath Foundry's own contract

Foundry hosts a server; the server still speaks the base Model Context
Protocol underneath, and that layer has its own sharp edge, independent of
which host launches it:

**A stdio server must never write anything to stdout that isn't a valid
protocol message.** The spec is explicit — a stray `print()` debug line, a
library that logs to stdout by default, even an unguarded warning — and
you've corrupted the newline-delimited JSON-RPC stream the client is trying
to parse. Logs go to stderr, always. This is easy to get right by
discipline and easy to violate by accident (a dependency that logs to
stdout on import, say), so it's worth a structural check rather than a
reminder: run the server's own module and confirm nothing lands on stdout
before the first real protocol message does.

**The Python SDK doesn't always return what you hand it, verbatim.** Feeding
a plain Python list back from a tool function gets auto-wrapped by the SDK
into `{"result": [...]}` on the wire rather than serialized as a bare JSON
array. If a caller — or a test — expects the bare-list shape the tool
function itself returns, the wrapping is invisible until something asserts
the actual wire payload instead of trusting the SDK's convenience layer.
Worth pinning the wire shape in a test explicitly rather than assuming the
SDK's ergonomic helpers preserve it.

**The installed SDK is a major version ahead of most public examples.**
`mcp` resolved to `2.0.0` here; a lot of example code circulating for this
protocol targets the 1.x line. Worth checking the installed package's own
source for a signature before trusting a snippet found outside it.

## What `mcp` actually costs the lockfile

Adding the `mcp` Python SDK is not a small dependency addition. Resolved
against this repo's existing pins, it pulls in — among others — a second
major version of `httpx` (`httpx2`, alongside the `httpx>=0.28,<0.29` this
repo already runs), `cryptography` (via `pyjwt[crypto]`, for a JWT-handling
path this read-only stdio server never exercises), `jsonschema`,
`opentelemetry-api`, `python-multipart`, `sse-starlette`, `starlette`, and
`uvicorn` with its full `[standard]` extra (`click`, `httptools`,
`uvloop`, `watchfiles`, `websockets`, `pyyaml`). That's real surface for a
server that never opens an HTTP port and never touches JWTs — the SDK
ships client, server, HTTP-transport, and auth code paths in one package,
and a stdio-only, read-only consumer inherits the lockfile weight of all of
it. In a repo that runs an OSV scan against its lockfile, that is a
meaningfully larger dependency surface to keep patched, not a free
addition.

One thing worth flagging rather than quietly living with: the pin that
shipped is `mcp>=2.0.0`, with no upper bound — looser than this repo's own
`>=x.y,<x.z` convention for every other dependency. An unbounded floor on a
package that pulls a crypto stack and a second HTTP major means the next
routine dependency refresh can land a new `mcp` major with none of the
scrutiny a version-bump PR would normally get. Worth tightening to match
the repo's convention the next time this dependency is touched.

## Why a monō foundry research pack ships inside this repository

This diff includes `.claude/skills/mono-foundry-context/` — a Claude Code
project skill, not a Foundry artifact, and easy to mistake for stray editor
configuration if nothing explains it. It's a curated reference pack built
from monō foundry's own published documentation at a pinned commit: the MCP
config contract, the skills-and-instructions contract, and a running note on
where the upstream docs have drifted or under-specified something. Every
Foundry-facing acceptance criterion behind this wedge — the config shape,
the discovery path, the frontmatter fields — traces back to that pack's
sources.

It ships for the same reason a bibliography ships with a research paper:
without it, a reader has no way to check the design decisions here against
what they were actually derived from, short of re-reading monō foundry's
docs from scratch at whatever commit happens to be current when they look —
which will not be the commit this wedge was built against. Shipping the
derivation source makes the wedge's design traceable. The chunked delivery
process that produced it is a different kind of object — internal working
notes describing versions of the code that no longer exist by the time
anyone reads them — and stays out of this diff for that reason; the pack
stays in because it is still true.

Two artifacts *were* deliberately left out of the pack even though the
upstream tooling would normally ship them: a large generated verification
script, and a handful of engine-internal scaffolding files. Both are
tooling-authored rather than research, and including them would have buried
the actually-authored reference material in noise attributed to nobody.

## The workspace-registration collision, accepted deliberately

`.mcp.json` lives at the repository root because that's where monō foundry's
own discovery expects it. It is also where a second, unrelated agentic
coding tool looks for its own MCP server registrations. Shipping the file
means any session of that second tool opened in this repository will prompt
to approve a server that was written for a completely different host.

Accepted as-is, for two reasons. First, blast radius: this is local
development tooling, not a deployed service, so the cost of the collision is
a one-time approval prompt, not an incident. Second, and more interesting:
the collision is itself a small piece of evidence that the interface is
genuinely standard rather than Foundry-specific — a second, independently
built agentic harness picking up the same registration file unprompted is
what "protocol, not platform" looks like in practice, not a bug to route
around.

## The honest-claims discipline, applied consistently

Nothing in this repository — the skill's own procedure text, the workspace
instructions, this document, or the engagement memo beside it — claims that
any Foundry artifact was exercised against a live monō foundry session. The
approved phrasing throughout is "validated against the documented contract
at the pinned commit," and it means exactly what it says: every acceptance
check that could run offline, against the pinned documentation and the
installed protocol SDK, did. The one check that requires an actual Foundry
runtime — does a real session actually launch this server, actually
discover this skill, actually respect the 30-second budget under load —
has not been run, because no live session was available. That gap is
disclosed here rather than papered over, and it's the natural next step for
anyone who does have one.
