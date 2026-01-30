from app.config import Settings
from app.github.client import GitHubClient
from app.llm.openai_client import OpenAIClient
from app.llm.prompt import SYSTEM_REVIEW, build_review_prompt

def _summarize_files(files: list[dict], max_files: int, max_chars: int) -> str:
    out = []
    used = 0
    for f in files[:max_files]:
        filename = f.get("filename")
        status = f.get("status")
        patch = f.get("patch") or ""
        chunk = f"\n---\nFile: {filename}\nStatus: {status}\nPatch:\n{patch}\n"
        if used + len(chunk) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                out.append(chunk[:remaining] + "\n...[truncated]...\n")
            out.append("\nNOTE: Output truncated due to size limits.\n")
            break
        out.append(chunk)
        used += len(chunk)
    if len(files) > max_files:
        out.append(f"\nNOTE: Only first {max_files} files included out of {len(files)}.\n")
    return "".join(out)

async def run_review(
    settings: Settings,
    gh: GitHubClient,
    llm: OpenAIClient,
    owner: str,
    repo: str,
    pr_number: int,
) -> str:
    pr = await gh.get_pr(owner, repo, pr_number)
    files = await gh.list_files(owner, repo, pr_number)
    files_summary = _summarize_files(files, settings.max_files, settings.max_patch_chars)

    prompt = build_review_prompt(pr.get("title", ""), pr.get("body", ""), files_summary)
    return await llm.chat(SYSTEM_REVIEW, prompt)
