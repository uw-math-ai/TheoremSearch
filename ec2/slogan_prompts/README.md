# How to create a `.prompt` configuration file

Each `.prompt` file is a **JSON object** with the following required keys:

| Key | Type | Description |
|-----|------|--------------|
| `prompt_id` | `string` | A short, unique identifier for the prompt version (e.g. `body-only-v1`). Must match file name. |
| `instructions` | `list[string]` | A list of guidelines or system-style instructions that define the model’s behavior. End sentences with periods. |
| `context` | `list[string]` | A list of column names in our `paper` or `theorem` tables in our RDS (e.g. `theorem.body` or `paper.summary`). See `rds_schema.sql` to see what columns we store. |

---

## Example

```json
{
    "prompt_id": "body-and-summary-v1",
    "instructions": [
        "You generate accurate summaries of math theorems based on theorem_body.",
        "You also consider paper_summary in your theorem summaries.",
        "Summaries are accurate and <= 4 sentences.",
        "Summaries are just sentences in ASCII, no Unicode.",
        "Describe but never reference the theorems with 'This theorem...' or similar.",
        "Avoid LaTeX and math symbols. Include identifiers that aid retrieval"
    ],
    "context": ["theorem.body", "paper.summary"]
}
