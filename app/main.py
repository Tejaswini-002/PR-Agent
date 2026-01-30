from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

from app.config import get_settings
from app.github.webhook import verify_signature
from app.github.auth import get_installation_token
from app.github.client import GitHubClient
from app.llm.openai_client import OpenAIClient
from app.core.reviewer import run_review
from app.core.commands import parse_command

load_dotenv()
settings = get_settings()

app = FastAPI(title="PR Agent (from scratch)")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhook/github")
async def github_webhook(req: Request):
    body = await req.body()
    sig = req.headers.get("X-Hub-Signature-256")
    if not verify_signature(settings.github_webhook_secret, body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = req.headers.get("X-GitHub-Event", "")
    payload = await req.json()

    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        return {"ok": True, "ignored": "no installation id"}

    token = await get_installation_token(settings, installation_id)
    gh = GitHubClient(token)
    llm = OpenAIClient(settings.openai_api_key, settings.openai_base_url, settings.openai_model)

    # PR opened/sync -> auto review
    if event == "pull_request":
        action = payload.get("action")
        if action in ("opened", "reopened", "synchronize"):
            pr = payload["pull_request"]
            owner = payload["repository"]["owner"]["login"]
            repo = payload["repository"]["name"]
            pr_number = pr["number"]

            review_md = await run_review(settings, gh, llm, owner, repo, pr_number)
            body = f"## 🤖 PR Agent Review\n\n{review_md}"
            await gh.create_comment(owner, repo, pr_number, body)
            return {"ok": True, "posted": "review"}

    # Commands from comments
    if event == "issue_comment":
        action = payload.get("action")
        if action == "created":
            comment_body = payload["comment"]["body"]
            cmd = parse_command(comment_body)
            if not cmd:
                return {"ok": True, "ignored": "no command"}

            # issue_comment can be on PRs or issues; check pull_request field
            issue = payload.get("issue", {})
            if "pull_request" not in issue:
                return {"ok": True, "ignored": "not a PR"}

            owner = payload["repository"]["owner"]["login"]
            repo = payload["repository"]["name"]
            pr_number = issue["number"]

            if cmd == "review":
                review_md = await run_review(settings, gh, llm, owner, repo, pr_number)
                await gh.create_comment(owner, repo, pr_number, f"## 🤖 PR Agent Review\n\n{review_md}")
                return {"ok": True, "posted": "review"}

            if cmd == "describe":
                # Simple describe using PR title/body; you can enhance with diff summary
                pr = await gh.get_pr(owner, repo, pr_number)
                desc = f"### PR Description\n\n**Title:** {pr.get('title')}\n\n{pr.get('body') or '(no description)'}"
                await gh.create_comment(owner, repo, pr_number, desc)
                return {"ok": True, "posted": "describe"}

    return {"ok": True, "ignored": "unsupported event/action"}
