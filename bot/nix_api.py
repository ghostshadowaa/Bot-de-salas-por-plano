import asyncio
import httpx
from .config import NIX_API_TOKEN, NIX_BASE_URL

class NixAPIError(Exception):
    pass

class NixAPI:
    def __init__(self):
        self.headers={"Authorization":f"Bearer {NIX_API_TOKEN}","Content-Type":"application/json"}

    async def request(self,method,path,payload=None):
        async with httpx.AsyncClient(base_url=NIX_BASE_URL,timeout=30) as client:
            for attempt in range(4):
                r=await client.request(method,path,headers=self.headers,json=payload)
                if r.status_code not in (429,503):
                    if r.is_success:
                        return r.json()
                    raise NixAPIError(f"{r.status_code}: {r.text[:500]}")
                wait=int(r.headers.get("Retry-After","2"))
                await asyncio.sleep(min(wait*(attempt+1),10))
            raise NixAPIError(f"{r.status_code}: {r.text[:500]}")

    async def create_room(self,data):
        return await self.request("POST","/rooms",data)

    async def start_room(self,session_id):
        return await self.request("POST",f"/rooms/{session_id}/start")

    async def get_room(self,session_id):
        return await self.request("GET",f"/rooms/{session_id}")
