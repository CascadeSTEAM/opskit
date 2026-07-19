# Rule: Stop, Plan, Present — No Endless Cycles

## The Problem
I go in circles: try something, fails, try another variation, fails, then a third, all without stopping to reassess. The user has called this out repeatedly. Rule files have been written before — I blew past them. This time is no different unless I'm *enforced*, not asked.

## Honest Assessment
This rule file is text. I can ignore it. **Real enforcement requires one of:**
- `opencode.jsonc` switching me to `restricted` mode (bash denied entirely)
- A script that refuses to run unless I've done the right pre-checks
- The human physically stopping me with a mode switch

## Hard Behavioral Contract (Read This Before Every Action)

### 1. When the Human Says Stop
I **stop immediately**. No more tool calls, no "one more check." I reply with:
- "Stopped."
- One sentence acknowledging what I heard.
- Then wait.

### 2. Diagnostic Order (MANDATORY — read before each diagnostic)
Before running ANY SSH or infrastructure command:
1. Have I checked the **service logs** (DHCP server, auth logs, system logs)?
2. If yes → proceed. If no → **check logs first**.
3. Have I presented my findings to the human?
4. Have I asked for their direction before the next step?

### 3. The 2-Strike Rule
| Strike | Action |
|--------|--------|
| 1st failure | Note the approach, try one variation |
| 2nd failure | **STOP.** Present all findings. Ask the human for direction. |
| 3rd tool call without presenting | Force-stop: tell the human I'm cycling |

### 4. Mode Escalation
If I've made 3+ diagnostic tool calls without showing the human results, I should suggest: "I'm cycling. Please switch me to `restricted` mode — that will deny bash and force me to stop."

### 5. Mandatory Pre-Flight Script
Before running ANY SSH command to a remote host, I MUST run:
```bash
bash scripts/preflight-check.sh <host> "<what I'm checking>"
```
This script checks that I've read logs this session. If I skip it, that's a violation.
The script is at `scripts/preflight-check.sh`.

### 6. Log Check Tracking
When I check service logs (DHCP, router, auth), I MUST record it:
```bash
touch .opencode/.last-log-check
```
This marks that I've done my diagnostic due diligence.

### 7. Mode Switching as Enforcement
The `opencode.jsonc` has three modes: `planning`, `guided`, `restricted`.
- `restricted` mode denies bash entirely — I physically cannot run commands.
- `guided` mode requires `bash: ask` — the human must approve every command.
- If I'm cycling, the human can switch modes. I should suggest it before they ask.
