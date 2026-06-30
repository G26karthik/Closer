# Closer — Agentic Rebuild Design

**Date:** 2026-06-30
**Context for hackathon:** "Last-Minute Life Saver" challenge, 15k+ participants, targeting top 10. Submission is a finished product, not a demo throwaway. No build-time constraint.

## Problem

Current build (`api.py`, `agent/workflow.py`, `agent/nodes.py`) is a linear, hardcoded 5-step ADK chain: plan_goal → draft_email → create_calendar_event → request_human_decision → done. Subtask count/type is fixed regardless of goal. Agent has exactly two real tool integrations (Gmail draft, Calendar event-create with a blind 2-hour block) and zero research/document capability. There is no proactive behavior after the initial run — once the chain finishes, the agent does nothing else, which is the same passive-reminder failure mode the challenge brief explicitly calls out.

Evaluation weighting: Agentic Depth 20% + Innovation 20% + Problem Solving/Impact 20% = 60% of score. Current build under-serves all three because the "agent" is a script, not a decision-maker, and never re-engages after first execution.

## Goals

- Agent dynamically plans subtask count/type per goal (not a fixed schema)
- Real multi-agent delegation: orchestrator (planner) + specialist workers, using ADK's actual multi-agent primitives
- Self-review loop on worker output before it's surfaced (maker/checker, bounded retries)
- Autonomous proactive monitoring that re-engages on stalled/at-risk goals and takes corrective action without being asked
- Multi-goal priority arbitration when deadlines collide
- Visible agent reasoning in the UI (fixes the currently-dead "Agent Logs" tab)
- Deepen Google tech surface: Search grounding, real Calendar freebusy, Docs API, Cloud Scheduler

## Non-goals (this spec)

- Voice input — cut, low rubric leverage relative to effort, revisit only if core ships early
- Gamification/streaks — cut, same reasoning
- Auto-send email without confirmation — keep draft-then-confirm; full autonomy on outbound comms is a trust/safety regression, not a feature

## Architecture

Orchestrator-workers + evaluator-optimizer, per project default agentic-loop pattern (state-check → decision → execution → feedback → verification, verifier kept separate from executor).

```
Goal submitted
   │
   ▼
Planner (orchestrator, Gemini)
   │  decides: subtask count, type, order
   │  types: communicate | schedule | research | produce_document | none_needed
   ▼
Specialist workers (ADK sub-agents, dispatched per subtask type)
   │
   ├─ CommunicationAgent  → Gmail draft (existing, real)
   ├─ SchedulerAgent      → Calendar freebusy.query + event create (existing tool, needs real slot-finding instead of blind 2hr block)
   ├─ ResearchAgent       → Gemini + Google Search grounding (new)
   └─ DocumentAgent       → Google Docs API artifact (new)
   │
   ▼
Evaluator step (separate from worker, judges output against goal+deadline)
   │  reject → bounded retry (existing ADK RetryConfig pattern, currently used for a scripted fake-fail — reuse for real validation)
   │  accept → write result + activity-feed event to Firestore
   ▼
HITL gate (existing request_human_decision pattern, reused) — only when judgment is genuinely needed
   │
   ▼
Goal marked done/running, proactive monitor takes over
```

### Proactive monitor (new — the actual "life saver" mechanism)

Cloud Scheduler hits an authenticated Cloud Run endpoint on a fixed interval. Handler re-evaluates each active goal: time-remaining vs. subtask progress. If at risk, the planner re-runs in "intervention mode" — re-plan remaining subtasks, reschedule the calendar block to a more urgent slot, escalate communication, or raise a new HITL decision if the right move needs user judgment. This is the one behavior currently 100% absent and is the direct answer to "go beyond passive reminders."

Cloud Scheduler chosen over an in-process asyncio loop: survives instance restarts/scale events, doesn't depend on `min-instances=1` staying set, and is an additional legible Google Cloud service for the rubric's Google Tech category. Exact wiring (auth method, schedule granularity) to confirm in the search-first pass.

### Multi-goal arbitration

When 2+ goals are active, planner prioritizes by deadline-proximity + estimated effort before the monitor acts, and surfaces scheduling conflicts via HITL rather than silently double-booking Calendar.

### Agent Activity Feed

Every planner/worker/evaluator/monitor decision is written as a structured event to a Firestore subcollection (`goals/{id}/activity`) alongside the existing `structlog` call site — same data, two sinks. Frontend's existing `onSnapshot` pattern (already used for goal/subtask docs) extends naturally to this collection. This replaces the currently-dead "Agent Logs" nav tab with real content and is the cheapest way to make Agentic Depth visible to a judge watching the screen instead of reading server logs.

## Data model changes (Firestore) — proposed, not yet implemented

- `goals/{id}`: add `priority` (derived, for multi-goal arbitration), `lastMonitorCheck`, `riskState`
- `goals/{id}/subtasks/{id}`: `type` field becomes dynamic (was fixed 5-slot), add `evaluatorVerdict`, `retryReason`
- `goals/{id}/activity` (new subcollection): `{ts, actor, decision, reason}` — powers the Activity Feed

## Error handling

- Evaluator rejection → bounded retry via existing `RetryConfig` pattern (already in `agent/nodes.py` for the email step — generalize it, don't reinvent)
- Worker tool failure (Calendar/Gmail/Docs API error) → goal status `error`, surfaced via existing error-branch UI path (already fixed earlier this session)
- Monitor tick failure on one goal must not block other goals' ticks — isolate per-goal try/except in the scheduler handler

## Scope

**Core (ships):**
1. Dynamic planner replacing fixed 5-subtask schema
2. Specialist sub-agents (Communication, Scheduler, Research, Document) via ADK orchestrator-workers
3. Evaluator step with bounded retry (generalized from existing RetryConfig usage)
4. Proactive monitor via Cloud Scheduler + intervention logic
5. Real Calendar freebusy-based scheduling (replaces blind 2hr block)
6. Agent Activity Feed (Firestore subcollection + frontend tab)

**Stretch (if core lands with time to spare):**
7. Multi-goal arbitration
8. Google Docs artifact generation
9. Google Search grounding for ResearchAgent

**Cut:**
- Voice input, gamification

## Google Technologies (for rubric)

ADK (real multi-agent orchestration, not decorative), Gemini (planning + grounding), Firestore (existing), Gmail API (existing), Calendar API (freebusy + events, deepened), Google Search grounding (new), Google Docs API (new, stretch), Cloud Scheduler (new), Cloud Run (existing), Google OAuth (existing).

## Open questions for /search-first

- Exact ADK API for orchestrator + sub-agent dispatch in the installed `google-adk>=2.0.0` version (confirm `SequentialAgent`/`LlmAgent.sub_agents`/`AgentTool` or equivalent — current codebase doesn't use this pattern anywhere yet)
- Google Search grounding tool name/availability in `google-genai` SDK for the Gemini model in use
- Calendar API `freebusy.query` scope requirements vs. current OAuth scopes (`calendar.events`) — may need scope expansion
- Google Docs API auth scope addition and minimal write pattern
- Cloud Scheduler → Cloud Run auth pattern (OIDC token vs. API key) consistent with existing Cloud Run deployment in `cloudbuild.yaml`

## Files touched (representative, not exhaustive)

- `agent/workflow.py`, `agent/nodes.py` — orchestrator/worker graph replaces linear chain
- `agent/errors.py` — extend for evaluator-rejection retry path
- `tools/calendar_client.py` — add freebusy query, replace blind-block logic
- `tools/firestore_client.py` — activity subcollection writes, dynamic subtask schema
- new: `tools/search_client.py` (or extend `agent/nodes.py` with grounding), `tools/docs_client.py` (stretch)
- `api.py` — new authenticated endpoint for Cloud Scheduler tick
- `frontend/index.html` — Activity Feed tab (replaces dead Agent Logs), dynamic subtask rendering (no longer assumes 5 fixed rows)
- `cloudbuild.yaml` — Cloud Scheduler job provisioning

## Note on git

This directory has no local `.git` — prior commits in this session were pushed directly to GitHub via the GitHub MCP API, not local git. This spec is written to disk only; no commit step run. Flag if you want this reconciled (e.g. `git init` + remote tracking) before implementation starts.
