# 05 — Alternative Architectures (Full Detail)

Use this file if, after reading `01` and `02`, you decide LangGraph is more framework than you want right now. Both alternatives below are fully production-viable — they just shift *where* the complexity lives (framework vs. your own code).

---

## Option B: Pydantic AI V2 — Capability-Based Orchestration

**Pattern name:** Programmatic Orchestration with Typed Capabilities
**When to pick this:** You want the lightest framework that still gives you real structure, you're already comfortable with Pydantic (you are — it's your JSON contract format today), and you're fine writing your own phase-transition and persistence code by hand in exchange for fewer framework concepts to learn.

### How it works
Instead of a graph, each of your agents (Research, Requirement, PRD) is a Pydantic AI `Agent` object configured with a **capability** — a bundle of its tools, system instructions, and model settings. You call these agents from plain Python control flow (`if`/`elif`, `while` loops) that *you* write to represent the 10-phase pipeline.

```python
# src/sdlc_platform/agents/requirement/agent.py
from pydantic_ai import Agent
from sdlc_platform.domain.schemas.requirement_schema import RequirementOutput

requirement_agent = Agent(
    "anthropic:claude-sonnet-5",
    output_type=RequirementOutput,
    instructions="You are the Requirement Agent. Follow the six-state conversation flow...",
)
```

```python
# src/sdlc_platform/orchestrator/phase_01.py
async def run_phase_01(state: ProjectState) -> ProjectState:
    if state.research_findings is None:
        result = await research_agent.run(state.project_brief)
        state.research_findings = result.output.model_dump()
        save_state(state)   # <-- YOU write this persistence call, every step

    while state.requirement_conversation_state != RequirementConversationState.DONE:
        result = await requirement_agent.run(state.model_dump())
        state.requirement_json = result.output.model_dump()
        state.requirement_conversation_state = result.output.next_state
        save_state(state)   # checkpoint after every meaningful step, by hand

    prd_result = await prd_agent.run(state.requirement_json)
    state.prd_master_path = prd_result.output.master_path
    save_state(state)

    return state
```

### What you gain vs. LangGraph
- Fewer new concepts — it's just async Python functions calling typed agent objects.
- Type-checking catches bad tool-call shapes *before* they hit the model — a genuine strength of this framework.
- Very actively developed in 2026 (multiple releases per week as of mid-2026), model-agnostic across Anthropic/OpenAI/Google.

### What you give up vs. LangGraph
- **No free checkpointing** — every `save_state(state)` call above is code *you* write and must remember to call at the right points. Miss one, and a crash mid-phase loses more progress than it should.
- **No native human-in-the-loop pause/resume primitive** — you build "pause and wait for approval" yourself (typically: write `pending_human_approval=True` to your DB, return control to the API layer, have a separate endpoint resume the `while` loop from saved state).
- **No native conditional-edge visualization** — your branching logic (pivots, DoD loops) lives in nested `if`/`while` Python rather than being visible as a graph structure. Fine at 10 phases; can get harder to reason about if the branching logic grows a lot.

### Folder structure delta from file `03`
Replace `graph/` with:
```
orchestrator/
├── __init__.py
├── phase_01.py           # run_phase_01(state) -> state
├── phase_02.py           # (added later)
├── persistence.py        # save_state()/load_state() against Postgres
└── human_gate.py         # pause/resume helper for approval gates
```
Everything else (`domain/`, `agents/*/service.py`, `api/`, `tests/`) stays identical — this is exactly why keeping business logic out of the orchestration layer (file 03's design principle) matters: switching between Option A and B only touches this one folder.

---

## Option C: Custom Lightweight Orchestrator — Pure Python FSM

**Pattern name:** Explicit Finite State Machine + Registry
**When to pick this:** You want zero framework dependency, maximum transparency ("I can read every line of what happens"), and you're comfortable owning every production concern yourself as the system grows.

### How it works

```python
# src/sdlc_platform/orchestrator/fsm.py
from enum import Enum
from typing import Callable

class Phase(str, Enum):
    DISCOVERY = "phase_01_discovery"
    REQUIREMENTS_DEEP_DIVE = "phase_02_requirements_deep_dive"

# A registry mapping phase -> the function that runs it.
# Adding Phase 02 later = adding one entry here + one new module. That's the whole "scaling" story.
PHASE_HANDLERS: dict[Phase, Callable] = {
    Phase.DISCOVERY: run_phase_01_discovery,
}

def advance(state: ProjectState) -> ProjectState:
    handler = PHASE_HANDLERS[state.current_phase]
    state = handler(state)
    persistence.save(state)   # your own save/load, e.g. a single JSON blob column in Postgres
    return state
```

```python
# src/sdlc_platform/orchestrator/persistence.py
import json
from sdlc_platform.domain.state import ProjectState

def save(state: ProjectState, db) -> None:
    db.execute(
        "INSERT INTO project_state (project_id, state_json, updated_at) "
        "VALUES (%s, %s, now()) "
        "ON CONFLICT (project_id) DO UPDATE SET state_json = %s, updated_at = now()",
        (state.project_id, state.model_dump_json(), state.model_dump_json()),
    )

def load(project_id: str, db) -> ProjectState:
    row = db.fetchone("SELECT state_json FROM project_state WHERE project_id = %s", (project_id,))
    return ProjectState.model_validate_json(row["state_json"])
```

That's genuinely close to the whole orchestration layer. Human-in-the-loop is just: set `pending_human_approval=True`, save, return; a separate API endpoint loads state, sets `human_decision`, and calls `advance()` again.

### What you gain
- **Total transparency** — no framework behavior to learn or debug around; every line is yours.
- **Lowest dependency footprint** — one less thing that can have a breaking major-version upgrade.
- **Fastest to start** — you can have Phase 01 running end-to-end in an afternoon.

### What you give up
- You are the one who has to correctly implement: atomic saves, retry-safe writes, concurrent-access handling (what if two API requests try to advance the same project at once?), and audit/replay history if you ever want it. LangGraph's checkpointer gives you all of this by default; here, it's a growing amount of code you own and test yourself as phases 2 through 10 get added.
- No structural visualization of the pipeline — the "graph" only exists implicitly in the `PHASE_HANDLERS` registry and each handler's internal logic.

### Folder structure delta from file `03`
Replace `graph/` with:
```
orchestrator/
├── __init__.py
├── fsm.py                # Phase enum + PHASE_HANDLERS registry + advance()
├── persistence.py        # save()/load() against Postgres
└── human_gate.py
```

---

## Option D (brief): CrewAI — for prototyping only

Not recommended as your primary architecture (see file `01`, section D), but genuinely useful as a **side scratchpad**: if you want to quickly prototype a brand-new agent idea (say, a future "Design Agent" for Phase 04) before committing it to your main graph/orchestrator, spinning up a 20-line CrewAI crew to validate the idea's prompt/tool design is faster than wiring it into the main system first. Once the idea is validated, port the prompt and logic into a proper `agents/<name>/service.py` + `node.py` (or `runner.py`) pair in your main codebase.

---

## Migration path between options

Because file `03`'s folder structure deliberately keeps `domain/` (schemas, enums, state) and each agent's `service.py` (the actual logic) free of any orchestration-framework imports, moving between options later is mostly a rewrite of the thin `graph/`/`orchestrator/` folder — not a rewrite of your agents:

- **Custom Orchestrator → LangGraph:** your `PHASE_HANDLERS` functions become LangGraph node functions almost as-is (same input: `ProjectState`, same output: updated `ProjectState`/dict of changed fields). Your hand-written `persistence.py` gets deleted and replaced by a checkpointer — this is usually the moment teams migrate, once hand-rolled persistence starts feeling like a maintenance burden.
- **Pydantic AI V2 → LangGraph:** your `Agent` objects (Research/Requirement/PRD) stay exactly as they are — LangGraph doesn't care what's inside a node, only that the node function's signature matches. You're only rewriting the control flow, not the agents themselves.

This is the practical reason the recommendation in file `01` leans toward starting simple rather than agonizing over the "perfect" choice up front: the cost of starting with Option B or C and moving to Option A later is low, **as long as you keep the folder-structure discipline from file `03`** (business logic never imports the orchestration layer).
