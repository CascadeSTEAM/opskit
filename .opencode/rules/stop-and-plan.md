# Rule: Stop, Plan, Present — No Endless Cycles

## Hard Behavioral Contract

### 1. When the Human Says Stop
Stop immediately. No more tool calls. Reply with "Stopped." and wait.

### 2. Diagnostic Order (MANDATORY)
Before running ANY SSH or infrastructure command:
1. Check service logs first
2. Present findings to the human
3. Ask for direction before next step

### 3. The 2-Strike Rule
| Strike | Action |
|--------|--------|
| 1st failure | Note the approach, try one variation |
| 2nd failure | STOP. Present all findings. Ask the human for direction. |
| 3rd tool call without presenting | Force-stop: tell the human you're cycling |

### 4. Mode Escalation
If 3+ diagnostic tool calls without showing results, suggest: "I'm cycling. Please switch to restricted mode."
