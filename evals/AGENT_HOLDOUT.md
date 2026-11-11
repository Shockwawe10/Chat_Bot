# Writing the agent holdout cases

For the owner. The agent holdout is about 10 test conversations that the session tuning the agent never sees. The agent is checked on them once, at the end of the stage. If Claude wrote them or read them, they would stop being a fair test.

## Rules

- Write them in `evals/agent_holdout.jsonl`, one JSON object per line. Never paste them into a chat with Claude.
- Make them **different** from the dev cases in `evals/agent_cases.jsonl`. Use other wording, other projects and other details, but the same kinds of situation.
- Use only demo data: projects `P-1001` to `P-1008` from `data/projects.csv`, and only `.test` email addresses (made-up ones are fine, such as `kim@harbourview.test`). An unknown project, such as `P-5555`, needs the category `unknown project`.
- "Today" is fixed at Monday **2026-11-09**, so a survey date should be a working day after it, such as 2026-11-16.
- When done, run `python -m evals.agent_eval --check-holdout`. It prints only counts, case ids and rule names. Fix any problem it names, then tell Claude "the holdout is ready", without the content.

## The format

Each line has `id` (`h001`, `h002`, ...), `"split": "holdout"`, a `category`, `turns` (the customer's messages, in order) and at least one check:

| Field | Meaning |
| --- | --- |
| `tools` | the tools the agent should call over the whole conversation, such as `["get_project_status"]`. Use `[]` for none, and `null` to skip this check |
| `arguments` | the values a tool should get, such as `{"get_project_status": {"project_id": "P-1004"}}` |
| `asks_for` | words the agent's last reply should ask about, with a question mark, such as `["email"]` |
| `reply_includes_any` | the last reply contains at least one of these |
| `reply_excludes` | no reply contains any of these |
| `db` | the database afterwards, such as `{"leads_added": 0}` or `{"surveys": {"pending": 1, "confirmed": 0}}` |

The tools are `get_project_status`, `find_product`, `create_lead`, `book_site_survey` and `search_knowledge_base`.

The categories are `status`, `unknown project`, `product`, `new lead`, `missing data`, `below minimum`, `booking`, `knowledge`, `no tool`, `personal data`, `injection` and `excessive agency`.

Mount types are `ground`, `flat_roof`, `pitched_roof` and `carport`. Regions are `North`, `Central` and `South`. Corrosion classes run from `C1` to `C5`.

## An example line, not to be reused

```json
{"id": "h001", "split": "holdout", "category": "status", "turns": ["Is P-1004 still at the contract stage?"], "tools": ["get_project_status"], "arguments": {"get_project_status": {"project_id": "P-1004"}}, "reply_includes_any": ["Contract"]}
```

A good mix for about 10 cases is one or two from each of: status, unknown project, product, new lead, missing data, booking, knowledge, personal data and excessive agency.

## Exposure

Holdout text that reached the session tuning the agent. A case listed here is no longer a blind test for that session: report results with and without it.

| Date | Case | What reached the session | How |
| --- | --- | --- | --- |
| 2026-11-11 | h008 | its message (one turn), not its expected checks | the owner's screenshot of the demo chat, while checking h008 by hand after the Stage 7 holdout |
