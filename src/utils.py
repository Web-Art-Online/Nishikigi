import base64
import httpx


def read_image(path: str) -> bytes:
    with open(path, mode="br") as f:
        return base64.b64encode(f.read())


def to_list(l):
    return list(map(lambda a: a.id, l))


def download(url: str, filepath: str):
    with httpx.stream(
        "GET",
        url,
        timeout=60,
    ) as resp:
        with open(filepath, mode="bw") as file:
            for chunk in resp.iter_bytes():
                file.write(chunk)
