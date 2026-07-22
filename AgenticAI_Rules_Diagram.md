# AI Sourcing Agent — Agentic AI Rules & Architecture Guide

**v1.0 Architecture** · 7 Build Rules · 6 Pre-Build Thinking Points · Before / During / Production Checklist

## Legend — Section Types

| Color | Meaning |
|---|---|
| 🟦 Blue | **Build Rule** — how to architect agents correctly |
| 🟩 Green | **Think First** — decisions before writing any code |
| 🟧 Orange | **During Build** — what to apply while coding |
| 🟥 Red | **Production** — what must be true before go-live |
| ⬛ Black | **Code example** — real implementation pattern |

---

## Part 1 — 7 Rules for Building Agentic AI That Scales

### Rule 1 — 💾 State is the Single Source of Truth
*Most Critical Rule*

> Every agent reads from state. Every agent writes back to state. Agents never call each other directly.

**✅ Correct pattern**
- Intake Agent writes `product_brief` to state
- Search Agent reads `product_brief` from state
- Search Agent writes `suppliers` to state
- Adding Agent 5 later — just reads existing state fields
- No existing agent is modified when new agent is added

**❌ Wrong pattern**
- Search Agent calls Intake Agent directly to get brief
- Agents share a mutable global object
- Agent passes result as function return to next agent

**State schema — each field owned by one agent**
```python
# sourcing state — complete schema
class SourcingState(TypedDict):
  # Intake Agent owns these
  product_brief:    Optional[dict]
  qa_history:       List[dict]

  # Search Agent owns these
  raw_suppliers:    List[dict]

  # Scoring Agent owns these
  ranked_suppliers: List[dict]

  # RFQ Agent owns these
  rfq_drafts:       List[dict]

  # Shared — any agent appends, none overwrites
  errors:           List[dict]
  agent_logs:       List[dict]
```

**Why this matters for multiple agents**
- **Adding agents** — When you add Verification Agent or Negotiation Agent later, they just read existing state fields. Zero changes to existing agents.
- **Debugging** — Any failure can be traced by reading the state object at the point of failure. Full history in one place.
- **Resume** — LangGraph checkpointer saves state to PostgreSQL. Buyer can resume mid-workflow days later — state is fully restored.

**Key pattern:** Agent → reads state → does work → writes state → next agent
**Never:** Agent A calls Agent B directly

---

### Rule 2 — 🎯 One Agent, One Responsibility
*Design Rule*

> If you cannot describe what an agent does in one sentence — it is doing too much.

**✅ Correct — split responsibilities**
- Intake Agent → extract structured brief from input
- Search Agent → find and return raw supplier list
- Scoring Agent → rank suppliers by 7 dimensions
- RFQ Agent → draft email content per supplier
- Outreach Agent → send approved emails only

**❌ Wrong — combined responsibilities**
- "Sourcing Agent" does intake + search + score + draft + send
- RFQ Agent also decides which suppliers to contact
- Search Agent also scores and ranks its own results

**Why it matters**
- When one agent fails — fix only that agent
- Each agent can be tested independently
- Each agent can be replaced without breaking others
- New agents can be inserted between existing ones

**Test yourself:**
- ✓ "This agent searches for suppliers" — one job, clear
- ✗ "This agent searches, scores, and drafts" — split it into 3

---

### Rule 3 — 📋 Define Agent Contracts Before Writing Code
*Contract Rule · Pydantic*

> Every agent has a typed input contract and typed output contract — written before any implementation.

**Input contract — what agent requires**
```python
class SearchAgentInput(BaseModel):
  product_brief: dict  # must exist
  max_results:   int = 20
  platforms:     List[str]

class RFQAgentInput(BaseModel):
  approved_suppliers: List[dict]
  product_brief:      dict
  buyer_identity:     dict  # name, title, email
```

**Output contract — what agent guarantees**
```python
class SearchAgentOutput(BaseModel):
  suppliers:          List[dict]
  total_found:        int
  platforms_searched: List[str]
  duration_ms:        int
  error: Optional[str] = None

# Output validated before next agent runs
# Pydantic raises if contract is violated
```

**Why contracts matter for multiple agents**
- **New agent** — When Verification Agent is added, it declares its input contract. Search Agent output already satisfies it — clean handoff with no changes.
- **Debugging** — Contract violation immediately tells you which agent produced bad output — not where it was consumed.

**Rule:** Write input + output Pydantic models for every agent before coding
**Rule:** Validate output before passing to next node — never trust silently

---

### Rule 4 — 🗺️ Orchestrator is Separate from Agents
*Architecture Rule · LangGraph*

> LangGraph graph only handles routing. Agent functions only handle their one job. Never mix them.

**Orchestrator — routing only**
```python
# graph.py — orchestrator
builder = StateGraph(SourcingState)

builder.add_node("intake", intake_node)
builder.add_node("search", search_node)
builder.add_node("scoring", scoring_node)
builder.add_node("rfq", rfq_node)

# Routing logic in orchestrator
builder.add_conditional_edges(
  "intake", route_after_intake,
  {"clarify": "clarification",
   "proceed": "search"}
)

# Adding new agent = 2 lines. Nothing else changes.
builder.add_node("verify", verify_node)
builder.add_edge("scoring", "verify")
```

**Routing function — decides next node**
```python
def route_after_search(state):
  errors = state.get("errors", [])
  search_err = [e for e in errors
                if e["node"] == "search"]

  if search_err:
    err_type = search_err[-1]["type"]
    if err_type == "zero_results":
      return "no_results_handler"
    return "error_handler"

  return "scoring"  # happy path
```

**Key insight**
- Agents know nothing about other agents
- Agents only know their own input and output
- Only the orchestrator knows the full graph

**Result:** Adding Agent N requires zero changes to Agents 1 to N-1
`add_node()` + `add_edge()` = new agent integrated

---

### Rule 5 — 🛡️ Every Agent Handles Its Own Failure
*Reliability Rule*

> No agent crashes the pipeline. Every error is caught, written to state, and routed by the orchestrator.

**Error handling pattern — every node**
```python
async def search_node(state):
  try:
    results = await search_suppliers(
      state["product_brief"]
    )
    if not results:
      # Zero results — not a crash
      return {**state,
        "suppliers": [],
        "errors": state["errors"] + [{
          "node": "search",
          "type": "zero_results"
        }]
      }
    return {**state, "suppliers": results}

  except Exception as e:
    # Write error, let orchestrator decide
    return {**state,
      "errors": state["errors"] + [{
        "node": "search",
        "type": "exception",
        "message": str(e)
      }]
    }
```

**Failure map for sourcing agent**
- Search returns 0 → notify Buyer, offer brief refinement
- All suppliers score low → warn before shortlist review
- Supplier email bounces → mark unreachable, notify Buyer
- Claude API times out → retry 3x, then pause + alert
- Quote reply unreadable → mark incomplete, draft follow-up
- Buyer never approves Gate → project stays pending, no timeout
- Session interrupted → resume from checkpointed state

**Pattern:** try → catch → write error to state → orchestrator routes to fallback
**Never:** let exception propagate and crash the pipeline

---

### Rule 6 — 🔒 Approval Gates Are Reusable Infrastructure
*HITL Rule · LangGraph `interrupt()`*

> Human approval is a system-level pattern — not coded inside individual agents. Every gate uses the same mechanism.

**Reusable gate class**
```python
class ApprovalGate:
  def __init__(self, gate_id, required_role):
    self.gate_id = gate_id
    self.required_role = required_role

  async def pause_and_wait(self, state, payload):
    await save_gate_state(
      self.gate_id,
      state["project_id"],
      payload
    )
    # LangGraph pauses here
    return interrupt({
      "gate_id": self.gate_id,
      "payload": payload,
      "required_role": self.required_role
    })

# All 3 gates use same pattern
gate_1 = ApprovalGate("shortlist", "buyer")
gate_2 = ApprovalGate("rfq_send", "buyer")
gate_3 = ApprovalGate("followup", "buyer")
# Future gate — one line
gate_4 = ApprovalGate("sample_req", "manager")
```

**Hard rule — enforced at DB level**
- ✗ Agent cannot write `approval_status` column — ever
- ✓ Only Buyer JWT can set approval_status = approved
- ✓ Outreach Agent reads the flag — never sets it
- ✓ Supabase RLS enforces this even if agent code is wrong

```sql
-- Supabase RLS — agent service key blocked
CREATE POLICY "only_humans_approve"
ON rfqs FOR UPDATE
USING (
  auth.jwt()->>'role'
  IN ('buyer', 'manager')
);
```

**3 gates in sourcing agent**
- 🔒 Gate 1 — confirm supplier shortlist
- 🔒 Gate 2 — approve RFQ before send
- 🔒 Gate 3 — approve follow-up emails

---

### Rule 7 — 📊 Log Everything — Centrally
*Observability Rule · `agent_runs` table*

> Every agent writes to the same logging system. Production agentic systems are black boxes without this.

**Central logger — used by every agent**
```python
class AgentLogger:
  async def log(self, project_id,
               node, event, data=None, error=None):
    await db.execute("""
      INSERT INTO agent_runs
      (project_id, node_name, event,
       data, error, timestamp)
      VALUES ($1,$2,$3,$4,$5,NOW())
    """, project_id, node,
    event, json.dumps(data), error)

# Every agent uses this — same table
logger = AgentLogger()

async def search_node(state):
  await logger.log(
    state["project_id"], "search", "started"
  )
  results = await search_suppliers(...)
  await logger.log(
    state["project_id"], "search",
    "completed",
    data={"found": len(results)}
  )
```

**What gets logged — 3 levels**
- Node level — started, completed, failed, duration
- Tool level — which tool called, input params, output
- LLM level — token count, latency, model used

**LangSmith — automatic tracing**
- Set `LANGCHAIN_TRACING_V2=true` in `.env`
- Every LLM call traced automatically
- Full visual of agent reasoning per run
- Token usage and cost per sourcing project

**`agent_runs` table structure**
- `project_id` · `node_name` · `event`
- `started_at` · `completed_at` · `duration_ms`
- `status` · `error` · `output_summary`

**Why this is non-negotiable**
Without logs — you cannot debug production agent failures.
With logs — trace exact path of every sourcing run in seconds.

---

## Part 2 — 6 Things to Think About Before Writing Code

### Think 1 — 🗂️ Agent Boundary Map — Where Does Each Agent Start and End?
*Design First*

> Draw a clear boundary before building. Unclear boundaries = state conflicts when agents overlap.

| Agent | Starts when | Ends when | Writes to state |
|---|---|---|---|
| 🟦 Intake Agent | User submits product input | Brief confirmed by user | `product_brief`, `qa_history` |
| 🟦 Clarification Agent | Brief has missing fields | All required fields filled | `qa_history`, `product_brief` |
| 🟩 Search Agent | Brief confirmed | Raw supplier list returned | `raw_suppliers` |
| 🟩 Scoring Agent | Raw list returned | Ranked shortlist ready | `ranked_suppliers` |
| 🟧 RFQ Agent | Gate 1 — shortlist approved | Gate 2 — RFQ draft approved | `rfq_drafts` |
| 🟧 Outreach Agent | Gate 2 passed | All RFQ emails sent + logged | `sent_emails`, `supplier_threads` |
| 🟥 Quote Agent | First supplier reply received | All quotes extracted or deadline hit | `quotes`, `follow_ups` |
| 🟥 Comparison Agent | All quotes ready or triggered by Buyer | Report generated | `comparison_report` |

**Rule:** If two agents share an unclear boundary — you will have state conflicts.
Each agent owns exactly the state fields it writes — no overlap.

---

### Think 2 — 🗃️ State Schema — Who Owns Each Field?
*Design First*

> Two agents writing the same field = race condition and data corruption. Design ownership before coding.

| State Field | Owned by | Read by | Access rule |
|---|---|---|---|
| `product_brief` | Intake Agent | All downstream agents | Only Intake writes. Others read-only. |
| `qa_history` | Clarification Agent | Intake Agent | Append only. Never overwrite. |
| `raw_suppliers` | Search Agent | Scoring Agent | Only Search writes. Scoring reads. |
| `ranked_suppliers` | Scoring Agent | RFQ Agent, Review UI | Only Scoring writes. Others read. |
| `rfq_drafts` | RFQ Agent | Outreach Agent, Review UI | Only RFQ Agent writes drafts. |
| `approval_status` | Buyer (human) | Outreach Agent (read-only) | Agent CANNOT write this. Ever. RLS enforced. |
| `quotes` | Quote Agent | Comparison Agent | Only Quote Agent writes. |
| `errors` | Shared | Orchestrator, all agents | Any agent appends. None overwrites. |

**Critical rule:**
✗ Two agents writing the same field = race condition
✓ One field, one owner, others read-only

---

### Think 3 — ⚡ Where Can the Pipeline Break — and What Happens?
*Failure Map*

> Map every failure point and its fallback before building. Unmapped failures become production incidents.

**Agent failures**
- Search returns 0 suppliers → notify Buyer, offer brief refinement
- All suppliers score below threshold → warn Buyer before showing shortlist
- RFQ Agent produces empty draft → retry with expanded prompt
- Outreach Agent email bounces → mark supplier unreachable, notify Buyer
- Quote reply is unreadable or non-English → mark incomplete, draft follow-up

**Infrastructure failures**
- Claude API timeout → retry 3x with backoff, then pause + alert
- Tavily API down → fallback to cached results or manual supplier add
- DB write fails → retry, log, surface error to admin
- Buyer never approves Gate → project stays pending, no automatic timeout
- Session interrupted mid-workflow → resume exactly from LangGraph checkpoint

**Rule:** If you have not mapped the failure — you have not finished designing.

---

### Think 4 — 🚧 Hard Limits — What Can the Agent Never Do?
*Safety Design*

> Write these as code-level constants and DB-level RLS policies — not documentation.

**System limits — enforced in code**
```python
HARD_LIMITS = {
  "max_suppliers_to_contact": 20,
  "max_followups_per_supplier": 2,
  "max_tokens_per_run": 50000,
  "max_retries_per_node": 3,
  "max_sourcing_runs_per_org_per_hour": 10,
}
```

**Agent action limits — what agent can NEVER do**
- Place a purchase order automatically
- Accept supplier payment terms
- Sign or agree to any contract
- Share confidential buyer data without explicit permission
- Send any email without human approval_status = approved
- Write to approval_status column — blocked by RLS
- Access users, billing, or org settings tables

**Where limits are enforced**
- Code constants — `HARD_LIMITS` dict
- Supabase RLS — DB-level block on sensitive columns
- Outreach Agent reads `approval_status` — never writes it

---

### Think 5 — 🔌 How Will You Add the Next Agent Without Breaking Existing Ones?
*Extensibility Test*

> This test must pass: adding Agent N requires zero changes to Agents 1 to N-1.

**Correct extension pattern — 4 steps only**
1. Add new field to `SourcingState` owned by new agent
2. Write new agent function with input/output contract
3. Register node: `builder.add_node("verify", verify_node)`
4. Add edge: `builder.add_edge("scoring", "verify")`
5. Done — no existing agent is modified

**Future agents already planned for sourcing**
- Supplier Verification Agent — checks legitimacy of top suppliers
- Negotiation Agent — assists with price/MOQ negotiation emails
- Sample Tracking Agent — monitors sample shipment status
- Shipping Agent — compares carrier rates post-supplier selection
- Tariff / Duty Agent — calculates import cost for shortlisted suppliers

**Warning sign — architecture is wrong if**
- Adding new agent requires editing existing agent code
- New agent needs to know internal details of other agents
- New agent shares a state field owned by another agent

**Extensibility test:**
✓ `add_node()` + `add_edge()` = new agent working in production
✗ If you edit existing agents to add a new one — redesign the state

---

### Think 6 — 🧪 How Will You Test Each Agent in Isolation?
*Testing Strategy*

> Every agent must be testable without running the full graph. No integration test required to validate one node.

**Isolated node test — no other agents needed**
```python
async def test_search_agent():
  # Mock state — only what Search Agent needs
  mock_state = SourcingState(
    project_id="test_001",
    product_brief={
      "category": "water bottles",
      "material": "stainless steel",
      "quantity": 500,
      "region": "China"
    },
    raw_suppliers=[],
    errors=[]
  )

  result = await search_node(mock_state)

  # Validate output contract
  assert len(result["raw_suppliers"]) > 0
  # Score is Scoring Agent's job — not Search
  assert all("score" not in s
             for s in result["raw_suppliers"])
```

**Testing checklist — per agent**
- Happy path — valid input → expected output
- Empty result — zero suppliers found → correct error written to state
- API failure — Tavily down → error in state, no crash
- Invalid input — missing required field → Pydantic raises
- Output contract — no fields outside agent's responsibility
- Retry — 3 failures → stops and writes error correctly

**Build order rule**
- Build and test Node 1 fully before wiring Node 2
- Wire graph only when all nodes pass isolation tests
- Integration test comes last — not first

**Rule:** Test each agent with mock state — no full graph run needed
**Warning:** If you can only test by running the full pipeline — split the agent

---

## ⚠️ Most Common Agentic AI Mistake

Building Agent 1 fast without designing the state schema and boundaries first. Then Agent 2 conflicts with Agent 1's state fields and requires a full rewrite. **Design state and boundaries completely before writing any agent code.**

*(Design first, then code)*

---

## Complete Checklist — Before Code · During Build · Before Production

### 📋 Before Writing Any Code
- [ ] Problem statement written in one sentence
- [ ] All agent boundaries defined — start and end
- [ ] Full state schema designed — one owner per field
- [ ] Input/output contracts written for every agent
- [ ] All failure points mapped with fallback defined
- [ ] Hard limits defined as constants
- [ ] Approval gate pattern designed as reusable class
- [ ] Extensibility test: adding Agent N = 2 lines only
- [ ] Interrupt/resume spiked and confirmed working

### 🔨 During Build
- [ ] One agent = one node = one responsibility
- [ ] Pydantic validation at every node output
- [ ] Structured JSON output from every LLM call
- [ ] Error written to state — never propagated raw
- [ ] Every agent tested in isolation before graph wiring
- [ ] Central AgentLogger used by every node
- [ ] Orchestrator routing separate from agent logic
- [ ] PostgreSQL checkpointer from day 1 (not in-memory)
- [ ] Context passed to each node is scoped — not full state dump

### 🚀 Before Production
- [ ] Retry with exponential backoff in every agent
- [ ] Token budget per run enforced and logged
- [ ] Rate limiting per org — Celery + Redis
- [ ] LangSmith tracing enabled — `LANGCHAIN_TRACING_V2=true`
- [ ] All hard limits enforced at DB level via Supabase RLS
- [ ] Interrupt/resume tested — user can resume days later
- [ ] SSE streaming — user sees real-time agent progress
- [ ] Health check endpoint covers all dependencies
- [ ] Agent runs in Celery task queue — not FastAPI request thread

---

## ✅ The Single Most Important Rule

Design the state schema and agent boundaries completely before writing any agent code. Everything else can be refactored. A bad state design requires rewriting every single agent.

*(State first, always)*

---

*AI Sourcing Agent · Agentic AI Rules & Architecture Guide v1.0 · 7 Build Rules · 6 Pre-Build Decisions · Full Checklist · For internal review and client presentation*
