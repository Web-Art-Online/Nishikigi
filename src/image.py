from datetime import datetime
import os

from botx.models import User
from jinja2 import Environment, FileSystemLoader, select_autoescape
import playwright.async_api
import qrcode


async def generate_img(
    id: int, user: User | None, contents: list, admin: bool = False
) -> str:
    env = Environment(
        loader=FileSystemLoader("templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=select_autoescape(
            [
                "html",
            ]
        ),
    )
    _contents = []
    for items in contents:
        values = [
            "__no_border__" if (len(items) == 1 and items[0]["type"] == "image") else ""
        ]
        for d in items:
            match (d["type"]):
                case "image":
                    if d["data"]["sub_type"] == 1:
                        # 表情包
                        values.append(
                            "_file://"
                            + os.path.abspath(f"./data/{id}/{d["data"]["file"]}")
                        )
                    else:
                        values.append(
                            "file://"
                            + os.path.abspath(f"./data/{id}/{d["data"]["file"]}")
                        )
                case "text":
                    values.append(d["data"]["text"].replace("\r\n", "\n"))
                case "face":
                    values.append(
                        "face://" + os.path.abspath(f"./face/{d["data"]["id"]}.png")
                    )
        _contents.append(values)
    # if user != None:
    #     url = f"https://3lu.cn/qq.php?qq={user.user_id}"
    #     qr = qrcode.QRCode(border=0)
    #     qr.add_data(url)
    #     img = qr.make_image(back_color="#f0f0f0")
    #     img.save(f"./data/{id}/qrcode.png")  # type: ignore

    output = env.get_template("normal.html" if user else "anonymous.html").render(
        contents=_contents,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        username=None if user == None else user.nickname,
        user_id=None if user == None else user.user_id,
        # qrcode=os.path.abspath(f"./data/{id}/qrcode.png") if user else None,
        admin=admin,
    )
    with open(f"./data/{id}/page.html", mode="w") as f:
        f.write(output)
    await screenshoot(id=id, output_path=f"./data/{id}/image.png")
    return os.path.abspath(f"./data/{id}/image.png")


async def screenshoot(id: int, output_path: str):
    async with playwright.async_api.async_playwright() as p:
        browser = await p.chromium.launch(headless=True, chromium_sandbox=True)
        page = await browser.new_page(
            viewport={"width": 720, "height": 720},
            device_scale_factor=3,
        )
        await page.goto(
            f"file://{os.path.abspath(f"./data/{id}/page.html")}",
            wait_until="networkidle",
        )

        # 在浏览器环境中计算页面实际高度并设置 div
        h = await page.evaluate(
            """
            () => {
                const doc = document.documentElement;
                const bod = document.body;
                const h = Math.max(
                    doc.scrollHeight, doc.offsetHeight, doc.clientHeight,
                    bod.scrollHeight, bod.offsetHeight, bod.clientHeight
                ) - 100;
                const el = document.querySelector('.blur-bg');
                el.style.height = h + 'px';
                return h;
            }
        """
        )

        # 如果页面高度过高，缩放页面以避免截图超时
        if h and h > 6000:
            scale = max(0.5, min(1.0, 6000 / h))
            h = await page.evaluate(
                """
                (scale) => {
                    document.body.style.zoom = scale;
                    const doc = document.documentElement;
                    const bod = document.body;
                    const h = Math.max(
                        doc.scrollHeight, doc.offsetHeight, doc.clientHeight,
                        bod.scrollHeight, bod.offsetHeight, bod.clientHeight
                    ) - 100;
                    const el = document.querySelector('.blur-bg');
                    el.style.height = h + 'px';
                    return h;
                }
            """,
                scale,
            )

        await page.screenshot(
            type="png",
            full_page=True,
            path=output_path,
            omit_background=True,
            animations="disabled",
            timeout=120000,
        )
        await browser.close()
