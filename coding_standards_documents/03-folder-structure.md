# 03 — Production Folder Structure

This layout works for the recommended LangGraph architecture, and needs almost no changes if you later pick one of the alternatives in file `05` (noted inline where it differs).

```
sdlc-agent-platform/
├── pyproject.toml                 # deps, tool config (ruff, mypy, pytest) — single source of truth
├── uv.lock                        # lockfile (or poetry.lock if you choose Poetry)
├── .env.example                   # documents required env vars, never commit real .env
├── .pre-commit-config.yaml        # ruff + mypy + pytest run before every commit
├── .github/
│   └── workflows/
│       └── ci.yml                 # lint + typecheck + test on every PR
├── Dockerfile
├── docker-compose.yml             # app + Postgres (checkpointer + app data) for local dev
├── README.md
│
├── src/
│   └── sdlc_platform/             # single installable package — avoids import path headaches
│       ├── __init__.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py        # pydantic-settings: all env-driven config in ONE typed object
│       │
│       ├── domain/                # framework-agnostic core types — the "business logic" layer
│       │   ├── __init__.py
│       │   ├── enums.py           # Zone, Phase, RequirementConversationState, etc.
│       │   ├── schemas/           # Pydantic contracts — the 14 information domains, DoD checklist, etc.
│       │   │   ├── __init__.py
│       │   │   ├── requirement_schema.py
│       │   │   ├── prd_schema.py
│       │   │   └── research_schema.py
│       │   └── state.py           # ProjectState — the single shared state model (see file 02, §3)
│       │
│       ├── agents/                # one subfolder per agent — mirrors your own mental model
│       │   ├── __init__.py
│       │   ├── research/
│       │   │   ├── __init__.py
│       │   │   ├── node.py        # LangGraph node function: research_node(state) -> dict
│       │   │   ├── prompts.py     # system prompt(s) — plain Python strings or loaded from prompts/*.md
│       │   │   ├── tools.py       # web-search tool wrapper(s) used by this agent
│       │   │   └── service.py     # pure logic, no LangGraph import — testable without the graph
│       │   ├── requirement/
│       │   │   ├── __init__.py
│       │   │   ├── node.py
│       │   │   ├── prompts.py
│       │   │   ├── question_bank.py   # your 14-domain question bank + done signals
│       │   │   └── service.py
│       │   └── prd/
│       │       ├── __init__.py
│       │       ├── node.py
│       │       ├── prompts.py
│       │       ├── writer.py      # master + version-sibling .md file writer
│       │       └── service.py
│       │
│       ├── graph/                 # the LangGraph wiring layer — thin, no business logic
│       │   ├── __init__.py
│       │   ├── build.py           # build_phase_01_graph(), later build_phase_02_graph(), etc.
│       │   ├── routers.py         # conditional-edge routing functions
│       │   ├── gates.py           # DoD checks + human-approval interrupt nodes
│       │   └── checkpointer.py    # returns SqliteSaver locally / PostgresSaver in prod
│       │
│       ├── integrations/          # anything talking to the outside world
│       │   ├── __init__.py
│       │   ├── llm_client.py      # thin wrapper around Anthropic/OpenAI SDK calls, with retry/backoff
│       │   ├── web_search.py      # Research Agent's underlying search provider
│       │   └── storage.py         # file/blob storage for generated PRD .md files
│       │
│       ├── api/                   # the HTTP layer (FastAPI) — talks to the graph, nothing else
│       │   ├── __init__.py
│       │   ├── main.py            # FastAPI app factory
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── projects.py    # start/resume a project
│       │   │   └── approvals.py   # human-in-the-loop approve/reject endpoint
│       │   └── deps.py            # shared FastAPI dependencies (DB session, graph instance)
│       │
│       └── observability/
│           ├── __init__.py
│           └── logging.py         # structured logger config (project_id, phase on every line)
│
├── prompts/                       # optional: keep long system prompts as versioned .md, imported by agents/*/prompts.py
│   ├── requirement_agent_system_prompt.md
│   ├── prd_agent_system_prompt.md
│   └── research_agent_system_prompt.md
│
├── knowledge_base/                 # your existing knowledge base + case library markdown specs live here
│   ├── sdlc_architecture_overview.md
│   ├── case_library/
│   └── phase_definitions/
│       └── phase_01_discovery.md
│
├── workspace/                      # RUNTIME OUTPUT — generated per-project artifacts (gitignored)
│   └── {project_id}/
│       ├── prd/
│       │   ├── master_prd.md
│       │   └── v2_billing_module_addition.md   # multi-version PRD siblings
│       └── research/
│           └── competitor_analysis.md
│
├── tests/
│   ├── unit/
│   │   ├── agents/
│   │   │   ├── test_requirement_service.py
│   │   │   ├── test_prd_writer.py
│   │   │   └── test_research_service.py
│   │   └── domain/
│   │       └── test_schemas.py
│   ├── integration/
│   │   └── test_phase_01_graph.py     # runs the real graph with a mocked LLM client
│   └── fixtures/
│       └── sample_requirement_json.json
│
└── scripts/
    └── run_local_project.py           # CLI helper: start a project against the graph locally
```

## Key decisions explained

- **`domain/` has zero LangGraph imports.** Your Pydantic schemas and enums are pure Python. This means you could swap the orchestration framework (per file `05`) later and only rewrite `graph/` + the `node.py` files — `domain/` and the `service.py` files underneath each agent stay untouched. This is the single most important structural decision for "easy to scale/change later."
- **`node.py` vs `service.py` split, per agent.** `node.py` is the thin LangGraph adapter (reads state, calls service, returns a dict). `service.py` is the actual logic and is 100% testable with plain `pytest`, no graph required. This mirrors clean-architecture "adapter vs core logic" separation without over-engineering it.
- **`prompts/` as versioned markdown, not inline strings**, matches your own existing practice of writing detailed markdown specs — and lets you diff prompt changes in git the same way you already diff PRD versions.
- **`workspace/` is gitignored runtime output** — this is where generated PRDs/research docs for actual end-user projects live, separate from `knowledge_base/` which holds *your own* meta-documentation about how the system itself is designed (the files this very report is part of).
- **One `pyproject.toml`, one lockfile.** Resist the urge to split into multiple packages/repos until you actually have a team-size reason to (e.g., a separate team wants an independent release cycle for one agent). Premature multi-repo/multi-package setup is a common way "simple" quietly becomes "complex."

## If you pick an alternative from file `05` instead

- **Pydantic AI V2:** identical folder structure, except `graph/` is replaced by `orchestrator/` containing your own FSM class + persistence code, and each `node.py` becomes `runner.py` (still: read state in, call service, write state out).
- **Custom Orchestrator:** same as above, but `orchestrator/` is even thinner — just a `fsm.py` (phase transition rules) and a `persistence.py` (save/load `ProjectState` as JSON rows in SQLite/Postgres).
