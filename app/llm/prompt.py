SYSTEM_REVIEW = """You are a senior code reviewer.
Be concrete and actionable. Focus on correctness, security, performance, readability, and tests.
If you are unsure, say what you need.
Output markdown with headings and bullet points.
"""

def build_review_prompt(pr_title: str, pr_body: str, files_summary: str) -> str:
    return f"""PR Title: {pr_title}

PR Description:
{pr_body or "(no description)"}

Changed Files (with patches):
{files_summary}

Write a helpful review comment:
- Summary
- Major issues (if any)
- Suggestions / improvements
- Tests to add
- Risks
"""
