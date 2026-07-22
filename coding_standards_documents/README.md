# Multi-Agent SDLC Automation System — Architecture Decision Report

**Prepared for:** Ankit's AI-driven SDLC Automation Platform
**Scope:** Architecture selection for the multi-agent system that powers the 10-phase / 3-zone SDLC model (Planning → Building → Shipping & Operations), starting with Phase 01 (Discovery: Requirement Agent, PRD Agent, Research Agent).
**Stack:** Python
**Goal:** A **simple**, **production-grade**, **easy-to-scale** architecture — not the most feature-rich one, not the most fashionable one.

---

## How to read this report

| File | What's in it |
|---|---|
| [`01-architecture-options-comparison.md`](./01-architecture-options-comparison.md) | Every architecture/framework option considered, scored against your actual requirements, with a decision matrix |
| [`02-recommended-architecture.md`](./02-recommended-architecture.md) | Deep dive on the **recommended** architecture — pattern, diagrams, state design, how your existing agents (Requirement/PRD/Research) plug in |
| [`03-folder-structure.md`](./03-folder-structure.md) | Full production folder structure with explanation of every directory |
| [`04-coding-standards-and-rules.md`](./04-coding-standards-and-rules.md) | Coding standards, linting/typing rules, agent-specific rules, testing rules, git rules |
| [`05-alternative-architectures.md`](./05-alternative-architectures.md) | Full detail on the two alternatives, in case you want to pick a different one — includes migration path between them |

Read them in order once, then use `03` and `04` as living reference documents during actual development.

---

## TL;DR Recommendation

**Pattern:** Hierarchical Supervisor Pattern, implemented as a **Directed State Graph**
**Framework:** **LangGraph** (Python, `langgraph` package)
**Why (one line):** Your system is not "a chat with agents" — it's a **10-phase pipeline with durable state, conditional branching (pivots, dependency deprecation), and human approval gates (Definition of Done)**. That is *exactly* the problem a graph-based state machine with a persistence layer is built to solve, and it is the most production-proven option available in 2026.

**Two credible alternatives are documented in full** (`05-alternative-architectures.md`) in case you want less framework and more raw Python:

1. **Pydantic AI V2** — lighter, type-safe, FastAPI-like. You hand-roll phase transitions and persistence yourself.
2. **Custom Lightweight Orchestrator** — zero framework dependency, plain Python + Pydantic + a small FSM class. Maximum simplicity, maximum code you own.

A one-line decision matrix (full version in file `01`):

| Criteria | LangGraph | Pydantic AI V2 | Custom Orchestrator |
|---|---|---|---|
| Fit for 10-phase pipeline w/ resumability | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| Simplicity to learn | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Production maturity (2026) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | N/A (you build it) |
| Built-in checkpointing / human-in-loop | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ (manual) |
| Vendor / model lock-in | None | None | None |
| Long-term maintenance cost | Low | Low-Medium | Medium-High (as it grows) |

**Bottom line:** Start with LangGraph, but use only the *simple subset* of it (single `StateGraph`, plain nodes, a SQLite checkpointer to start). Don't reach for its advanced features (subgraph parallelism, complex reducers, streaming modes) until you actually need them. That gives you production infrastructure (checkpointing, resumability, human-in-the-loop) for free, without the complexity, because you're only using 20% of the framework's surface area.

---

## Assumptions made

Since you didn't specify these, the report assumes:

- **Python 3.12+**, dependency management via `uv` (fast, 2026 industry-default; `poetry` noted as an equally valid alternative).
- You will use **one or more hosted LLM APIs** (Anthropic Claude and/or OpenAI) rather than self-hosted open-weight models — the recommended architecture stays model-agnostic either way.
- A **single small team / solo builder** to start, not a 20-person platform team — this is why "simple" is weighted heavily in the scoring.
- The system should be deployable as **one service to begin with**, with a clear path to splitting into microservices later if load demands it.

If any of these are wrong, flag it — the recommendation may shift slightly (noted in file `01` under "when to reconsider").
