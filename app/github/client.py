import httpx

class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr(self, owner: str, repo: str, number: int) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/repos/{owner}/{repo}/pulls/{number}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def list_files(self, owner: str, repo: str, number: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/repos/{owner}/{repo}/pulls/{number}/files", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def create_comment(self, owner: str, repo: str, number: int, body: str) -> None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.base}/repos/{owner}/{repo}/issues/{number}/comments",
                headers=self.headers,
                json={"body": body},
            )
            r.raise_for_status()
