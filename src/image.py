from datetime import datetime
import os

from botx.models import User
from jinja2 import Environment, FileSystemLoader
import playwright.async_api


async def generate_img(id: int, user: User | None, contents: list) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    values = []
    for d in contents:
        match (d["type"]):
            case "image":
                values.append(
                    "file://"
                    + os.path.abspath(f"./data/{id}/{d["data"]["file"]}")
                )
            case "text":
                values.append(
                    d["data"]["text"].replace("\r\n", "\n").replace("\n", "<br>")
                )
            case "face":
                values.append(
                    "face://" + os.path.abspath(f"./face/{d["data"]["id"]}.png")
                )
            case "br":
                values.append("<br>")

    output = env.get_template("normal.html" if user else "anonymous.html").render(
        contents=values,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        username=None if user == None else user.nickname,
        user_id=None if user == None else user.user_id,
    )
    with open(f"./data/{id}/page.html", mode="w") as f:
        f.write(output)
    await screenshoot(id=id, output_path=f"./data/{id}/image.png")
    return os.path.abspath(f"./data/{id}/image.png")


async def screenshoot(id: int, output_path: str):
    async with playwright.async_api.async_playwright() as p:
        browser = await p.chromium.launch(headless=True, chromium_sandbox=True)
        page = await browser.new_page(
            java_script_enabled=False, viewport={"width": 720, "height": 200}
        )
        await page.goto(f"file://{os.path.abspath(f"./data/{id}/page.html")}")
        await page.screenshot(
            type="png",
            full_page=True,
            path=output_path,
            omit_background=True,
            animations="disabled",
        )
        await browser.close()
