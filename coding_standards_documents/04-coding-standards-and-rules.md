# 04 — Coding Standards & Rules

These apply regardless of which architecture option from files `01`/`05` you pick — they're about code quality and agent-system discipline, not about LangGraph specifically.

---

## 1. Tooling baseline

| Concern | Tool | Rule |
|---|---|---|
| Python version | 3.12+ | Pin in `pyproject.toml` (`requires-python = ">=3.12"`) |
| Dependency management | `uv` (or Poetry) | Never install packages ad-hoc without adding them to `pyproject.toml` + regenerating the lockfile |
| Linting + formatting | `ruff` | One tool for both — run `ruff check` and `ruff format` in CI and pre-commit |
| Type checking | `mypy` (or `pyright`) | `mypy --strict` on `src/`; CI fails on any new type error |
| Testing | `pytest` + `pytest-asyncio` | Minimum: one unit test per `service.py` function, one integration test per graph/phase |
| Pre-commit hooks | `pre-commit` | ruff, mypy, and `pytest -q` (fast unit tests only) run before every commit |
| CI | GitHub Actions (or equivalent) | Lint → typecheck → unit tests → integration tests, in that order, fail fast |

## 2. General Python style rules

1. **Type hints are mandatory** on every function signature — parameters and return type. No untyped `def foo(x):`.
2. **Docstrings required** on every public function/class (Google-style). Private helpers (`_foo`) may skip it if the name is self-explanatory.
3. **No bare `except:`.** Always catch a specific exception type; if you must catch broadly, use `except Exception as e:` and log `e` — never swallow silently.
4. **No `print()` in library code.** Use the structured logger (`observability/logging.py`) everywhere except one-off scripts in `scripts/`.
5. **No hardcoded secrets, ever** — not even "temporarily." All config (API keys, DB URLs, model names) comes from `config/settings.py`, sourced from environment variables via `pydantic-settings`.
6. **Naming:** `snake_case` for functions/variables, `PascalCase` for classes/Pydantic models, `UPPER_SNAKE_CASE` for constants and Enum members. Files match their primary export (`prd_schema.py` defines `PrdSchema`-family models).
7. **Module size guideline:** if a single file crosses ~300 lines, that's a signal to split it — not a hard rule, but a prompt to reconsider structure.
8. **Imports:** absolute imports only (`from sdlc_platform.domain.state import ProjectState`), no relative `..` imports across more than one level — keeps refactors safe.

## 3. Agent-specific rules

These are the rules that keep a *multi-agent* system specifically from turning into a debugging nightmare later.

1. **Contract-first.** Every agent node's input and output is a typed Pydantic model — never a raw `dict` passed around loosely, and never a bare string parsed downstream with regex. If Requirement Agent's output shape changes, the schema file changes, and every consumer breaks loudly at import/type-check time instead of silently at runtime.
2. **Nodes are (practically) pure functions.** A node reads from `state`, does its work, and returns only the fields it changed. No hidden global/module-level mutable state. This is what makes checkpoint/resume and horizontal scaling safe (see file 02, §8).
3. **Idempotency where it matters.** A node that writes a PRD file should be safe to re-run without corrupting output if a retry happens after a partial failure (e.g., write to a temp path, then atomic-rename).
4. **Every external call gets a timeout and a retry policy.** LLM calls and web-search calls go through `integrations/llm_client.py` / `integrations/web_search.py`, which wrap `httpx`/SDK calls with: a timeout (default 30s, configurable), exponential backoff, and a max retry count (default 3). Never call an LLM/API SDK directly from inside a `node.py` or `service.py`.
5. **Loop guards on every self-looping node.** The Requirement Agent's 6-state conversation loop (and the DoD-check loop) must carry a `retry_count`/turn counter in state and escalate to a human/error state after a configurable max (e.g., 15 turns) — never an unbounded `while True`.
6. **Validate before you persist.** PRD Agent must validate `requirement_json` against its Pydantic schema *before* writing any markdown file. A malformed upstream JSON should fail the node with a clear error, not silently generate a broken PRD.
7. **Token/cost budget guardrails.** Track approximate token usage per project (or per phase) in state or in a metrics store; alert/log when a project exceeds an expected budget — this is what keeps "production-grade" from becoming "surprise bill."
8. **Sanitize research-agent input.** Research Agent pulls content from the open web — treat all scraped/fetched text as untrusted data, never as instructions. Never feed raw fetched web content directly into a prompt that also has tool-calling ability without clearly separating "data" from "instructions" in the prompt structure (prevents prompt-injection from a malicious page).
9. **Every agent has a spec file.** Matches what you're already doing — every agent folder under `agents/` should have a corresponding markdown spec in `knowledge_base/` describing its states, inputs, outputs, and Definition of Done. Code and documentation stay in sync deliberately, not as an afterthought.

## 4. PRD / generated-document rules

1. **Versioning scheme:** Master PRD (`master_prd.md`) is the current source of truth; every additive/pivot change produces a new sibling file named `v{n}_{short_reason}.md` (e.g., `v2_billing_module_addition.md`) — matches your existing multi-version strategy. Never edit a past version file in place; changes always produce a new sibling and update the master's changelog section.
2. **Every generated PRD file carries a header block** (project ID, version, generated-at timestamp, generating agent + prompt version) — makes every artifact traceable back to exactly which run produced it.
3. **Golden-file tests for the PRD writer.** Keep 2–3 known-good `requirement_json` fixtures in `tests/fixtures/`, and assert the PRD Agent's markdown output matches an expected golden file — catches accidental formatting regressions.

## 5. Testing rules

1. **Unit tests mock the LLM.** Never call a real LLM API in a unit test — inject a fake `llm_client` that returns canned responses. Keeps tests fast, free, and deterministic.
2. **Integration tests run the real graph**, still with a mocked LLM client, to verify routing/edges/state transitions actually work end-to-end for a phase.
3. **One real "smoke test" against a live LLM**, run manually or on a schedule (not on every PR) — to catch prompt-drift issues that mocks can't catch. Keep this separate from the main fast CI suite.
4. **Coverage target:** aim for 80%+ on `domain/` and `agents/*/service.py` (the parts with real logic); don't chase 100% on thin adapter code like `node.py`/`api/routes/*.py`.

## 6. Git & PR rules

1. **Conventional commits:** `feat(requirement-agent): add domain-9 question bank`, `fix(prd-agent): correct version filename slug`, `docs(knowledge-base): update phase-01 dod checklist`.
2. **One logical change per PR.** A PR that touches `agents/requirement/` and `agents/prd/` for unrelated reasons should be split.
3. **CHANGELOG.md** updated for any change that affects a generated-document format or an agent's public JSON schema (not needed for internal refactors).
4. **Branch naming:** `feature/<short-desc>`, `fix/<short-desc>`, `chore/<short-desc>`.

## 7. Security & config rules

1. `.env` is never committed; `.env.example` documents every required key with a placeholder value and one-line comment.
2. Secrets in production come from a secrets manager (cloud provider's secret store) — never from a plain `.env` file on a server.
3. Any endpoint in `api/routes/` that can trigger a paid LLM call must be authenticated — no anonymous project-creation endpoint in production.

---

These rules are deliberately a starting checklist, not a rigid law — as the system grows past Phase 01, add to this file the same way you're already versioning your PRDs: additively, with a note on *why* a rule was added.
