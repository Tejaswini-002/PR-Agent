import time
import jwt  # PyJWT
import httpx

from app.config import Settings

def make_jwt(settings: Settings) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, settings.github_private_key_pem, algorithm="RS256")

async def get_installation_token(settings: Settings, installation_id: int) -> str:
    gh_jwt = make_jwt(settings)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {gh_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers)
        r.raise_for_status()
        return r.json()["token"]
