import base64
import httpx


def read_image(path: str) -> bytes:
    with open(path, mode="br") as f:
        return base64.b64encode(f.read())


def to_list(l):
    return list(map(lambda a: a.id, l))


async def download(url: str, filepath: str):
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()

            with open(filepath, mode="wb") as file:
                async for chunk in resp.aiter_bytes():
                    file.write(chunk)
