# 01 — Architecture Options Comparison

## 1. What does *your* system actually need from an architecture?

Before comparing frameworks, it's worth being explicit about the requirements — pulled directly from what's already been designed:

| Requirement | Why it matters here |
|---|---|
| **Multi-step, long-running pipeline** | 10 phases across 3 zones. A single "project" can take days/weeks to move through Discovery → Planning → Build → Ship. |
| **Durable, resumable state** | A user can start Phase 01, close the laptop, come back tomorrow. The system must resume exactly where it left off — not restart. |
| **Structured JSON as the inter-agent contract** | Already decided: Requirement Agent emits JSON, PRD Agent consumes it. The architecture must make typed data-passing between agents a first-class citizen, not an afterthought. |
| **Conditional branching / change management** | Real edge cases already modeled: a billing module added mid-build, a core AI model deprecated mid-project. The architecture needs conditional routing, not just a straight line. |
| **Human-in-the-loop checkpoints** | Phase 01 Definition of Done is a formal gate — the system must be able to pause, wait for human approval, and only then proceed. |
| **Independent, swappable agents** | Requirement Agent, PRD Agent, and Research Agent are separate concerns today; more phase-agents will be added later (Phase 02 onward). Adding a new agent shouldn't require rewiring the whole system. |
| **Simplicity** | Explicitly requested — no framework magic that can't be explained on a whiteboard in 5 minutes. |
| **Production-grade + scalable** | Needs to survive real usage: retries, logging, observability, horizontal scaling — not just a notebook demo. |

This list is the scoring rubric used below.

---

## 2. Candidate architectures considered

### A. LangGraph — Graph-Based State Machine *(recommended — see file 02)*
Models the system as a **directed graph**: nodes = agents/steps, edges = transitions (including conditional edges), a shared typed **State** object flows through the graph. Built-in checkpointing persists state after every node, enabling exact resume, time-travel debugging, and human-in-the-loop interrupts.

- **Orchestration model:** directed graph with conditional edges
- **State persistence:** built-in checkpointer (SQLite for dev, Postgres for production), with time-travel/replay
- **Human-in-the-loop:** native `interrupt()` support — pause a graph, wait for approval, resume
- **Model dependency:** none — works with any LLM provider (Claude, OpenAI, local models)
- **Maturity (2026):** GA since October 2025, actively maintained, most-cited framework for production stateful multi-agent workflows in 2026 comparisons; surpassed CrewAI in adoption during early 2026, largely because its graph model maps cleanly to audit trails and rollback — exactly what regulated/production teams need.
- **Learning curve:** moderate — you need to understand `StateGraph`, nodes, edges, and checkpointers. Steeper than CrewAI or Pydantic AI, but the concepts map 1:1 to what you've already designed (your 3 zones and 10 phases *are* a graph).
- **Downside:** more moving parts than a plain function-calling script if used at full complexity. Mitigated by only using the simple subset (see file 02).

### B. Pydantic AI V2 — Capability-Based Agent Framework
A lighter framework from the Pydantic team (same team behind FastAPI's validation layer). In v2 (June 2026), every agent extension point — tools, instructions, hooks, model settings — collapses into a single primitive called a **capability**. The core stays deliberately small; more features live in an optional companion package (the "Harness").

- **Orchestration model:** linear/programmatic — you call agents from regular Python code (`if`/`else`, `while` loops), there's no built-in graph or state machine
- **State persistence:** none built-in — you'd store phase state and JSON contracts yourself (e.g., in Postgres) and write the resume logic by hand
- **Human-in-the-loop:** no native pause/resume primitive — achievable, but you build it
- **Model dependency:** none — model-agnostic (Anthropic, OpenAI, Google, and more, each opt-in)
- **Maturity (2026):** very actively developed — reached stable v2.0 on June 23, 2026 and shipped five further releases in the following ten days. Type safety is its strongest selling point: bad tool-call shapes get caught before they ever reach the LLM.
- **Learning curve:** low — if you already know Pydantic (which you already use for your JSON schemas), this feels native.
- **Downside:** since it's linear rather than graph-based, YOUR 10-phase/3-zone structure has to be encoded as your own control-flow code + your own persistence layer. Good if you want full control; more code you own.

### C. Custom Lightweight Orchestrator — Pure Python
No framework at all. A small `Enum`-based phase state machine class, Pydantic models for every agent's input/output contract, and a simple persistence layer (SQLite file or JSON-on-disk to start, Postgres later).

- **Orchestration model:** hand-written FSM (finite state machine) — you define phase transitions explicitly
- **State persistence:** you build it (usually ~100–150 lines: a `save_state()`/`load_state()` pair around a Pydantic model)
- **Human-in-the-loop:** trivial to add (it's just "stop the loop, wait for an approval flag in the DB")
- **Model dependency:** none
- **Maturity:** N/A — it's your own code, so "maturity" = your own test coverage
- **Learning curve:** lowest of all three — it's just Python classes and functions
- **Downside:** every production concern (retries, checkpointing, concurrency, observability) is something *you* write and maintain. Fine at small scale; becomes a growing tax as more phases/agents are added.

### D. CrewAI — Role-Based Crews *(considered, not recommended as primary)*
Models agents as a "crew" with roles (e.g., "Researcher", "Writer") and a process type (sequential or hierarchical). Fastest framework to get a working demo in.

- **Why it's tempting:** genuinely the quickest path from zero to "agents talking to each other," strong for role-based collaboration, growing plugin ecosystem (pluggable memory/RAG backends as of v1.14, May–June 2026).
- **Why it's not the primary pick here:** CrewAI's model is "a team collaborating on one task," not "a strict, resumable, auditable pipeline with approval gates." It has weaker built-in support for the kind of long-lived, checkpointed, conditionally-branching state machine your 10-phase model needs. You *can* force it to do this, but you'd be fighting the abstraction rather than using it.
- **When to reconsider it:** if you ever build a rapid internal demo/prototype of a *new* agent idea before committing it to the main graph, CrewAI is a genuinely good scratchpad tool for that side-exploration.

### E. Claude Agent SDK — Anthropic-Native Hierarchical Sub-Agents *(considered, not recommended as primary)*
Anthropic's own SDK for building production agents on the same runtime that powers Claude Code — a lead agent that can spawn child sub-agents (hierarchical, up to several levels deep as of the June 2026 update), each with an isolated context window and its own tools.

- **Why it's tempting:** if you commit fully to Claude models, this gives you hosted session management, subagent fan-out, and cost attribution per agent essentially for free.
- **Why it's not the primary pick here:** (1) it ties you to Claude models only — you lose model-agnosticism; (2) its sweet spot is *dynamically decomposable* tasks (e.g., "review this codebase" → fan out N sub-agents), not a *fixed* 10-phase document-generation pipeline with durable cross-session state and formal Definition-of-Done gates. Your system is closer to a compliance workflow than an open-ended research task.
- **Good hybrid idea for later:** your **Research Agent** specifically *is* an open-ended, fan-out-friendly task ("search the web, analyze competitors, come back with a synthesis"). Nothing stops you from calling into a Claude Agent SDK-style sub-agent *from inside a single LangGraph node* for just that one phase. Keep the outer skeleton (LangGraph) simple; use the right tool inside a node when a node's job genuinely benefits from it.

### F. Not evaluated in depth (out of scope for a Python, model-agnostic system)
- **Microsoft Agent Framework** (merger of Semantic Kernel + AutoGen, April 2026) — best for teams on the Microsoft/.NET stack; adds little for a pure-Python, non-Azure project.
- **Google ADK** — hierarchical agent tree, tightly coupled to Vertex AI/Gemini; a good architecture *shape* (root → sub-agents, similar to your zones → phases idea) but the vendor coupling isn't a fit unless you commit to Google Cloud + Gemini.
- **AutoGen (legacy)** — Microsoft placed it in maintenance mode in favor of Microsoft Agent Framework; not a forward-looking choice for a new build in 2026.

---

## 3. Decision matrix

Weighted scoring (1–5, 5 = best) against the requirements from Section 1. Weights reflect what you emphasized: simplicity and production-readiness matter most; raw feature count matters least.

| Requirement | Weight | LangGraph | Pydantic AI V2 | Custom Orchestrator | CrewAI |
|---|---|---|---|---|---|
| Resumable, durable, long-running state | 3 | 5 | 2 | 3 | 2 |
| Structured JSON contracts between agents | 2 | 5 | 5 | 5 | 3 |
| Conditional branching / change management | 3 | 5 | 3 | 4 | 2 |
| Human-in-the-loop gates | 3 | 5 | 2 | 3 | 2 |
| Adding new phase-agents later without rewiring | 2 | 5 | 4 | 3 | 3 |
| Simplicity to learn & explain | 3 | 3 | 4 | 5 | 4 |
| Production maturity in 2026 | 2 | 5 | 4 | 2 | 4 |
| **Weighted total (max 90)** | | **83** | **56** | **62** | **48** |

LangGraph wins clearly once resumability and human-in-the-loop gates are weighted properly — those two requirements alone are core to your Phase 01 Definition-of-Done design and your multi-version PRD / mid-build pivot handling.

---

## 4. Final recommendation

**Use LangGraph**, but treat it as "just a state machine with free persistence" rather than "a big AI framework." Concretely:

- Use exactly one `StateGraph`.
- Use plain Python functions as nodes (no need for LangGraph's chat-agent abstractions if you don't want them — a node can just call the Anthropic/OpenAI SDK directly).
- Use the SQLite checkpointer locally, Postgres checkpointer in production — this single feature (free, durable, resumable state) is the main reason to pick this framework over the alternatives.
- Everything else in the framework (subgraph parallelism, complex streaming modes, multi-agent swarms) — ignore until you have a concrete need for it.

Full implementation detail: → `02-recommended-architecture.md`

---

## 5. When to reconsider this decision

Revisit this choice if any of the following becomes true later:

- **You move away from Python entirely** (e.g., a hardened, high-throughput production rewrite in Go) — out of scope for this report, noted only for completeness.
- **The pipeline stops being a fixed set of phases** and becomes genuinely open-ended/dynamic (i.e., the system itself decides how many agents to spawn per project, not just which of 10 known phases to run) — at that point look again at Claude Agent SDK–style dynamic sub-agent fan-out, potentially *combined with* LangGraph as the outer skeleton.
- **You need massive horizontal scale with independent teams owning independent phases as separate microservices** — LangGraph still works here (each phase can become its own deployed graph/service), but at that scale also revisit an event-driven backbone (a message queue between phase-services) rather than in-process graph edges.
- **You genuinely never need to resume a project across sessions** (e.g., everything always completes in one sitting) — in that unlikely case, the Custom Orchestrator's simplicity becomes more attractive since you'd be paying for checkpointing you don't use.
