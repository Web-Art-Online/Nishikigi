from datetime import datetime
import os

import config

from botx.models import User
from jinja2 import Environment, FileSystemLoader, select_autoescape
import playwright.async_api
from PIL import Image


async def generate_img(
    id: int, user: User, anonymous: bool, contents: list, admin: bool = False
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
                    values.append(
                        d["data"]["text"]
                        .replace("\r\n", "\n")
                        .replace("\n", "__internal_br__")
                    )
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

    output = env.get_template("normal.html").render(
        contents=_contents,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        username=user.nickname,
        user_id=user.user_id,
        # qrcode=os.path.abspath(f"./data/{id}/qrcode.png") if user else None,
        admin=admin,
        id=id,
        anonymous=anonymous,
        bg_img=(
            os.path.abspath(f"./data/bg/{user.user_id}.png")
            if os.path.exists(f"./data/bg/{user.user_id}.png")
            else None
        ),
    )
    with open(f"./data/{id}/page.html", mode="w") as f:
        f.write(output)
    tmp_file = f"./data/{id}/tmp.png"

    await screenshoot(id=id, output_path=tmp_file)
    img = Image.open(tmp_file)

    # 定义裁切区域 (left, upper, right, lower)
    # 左上角为 (0,0)
    crop_box = (0, 0, img.size[0] - 64, img.size[1] - 64)
    # 裁切图片
    cropped_img = img.crop(crop_box)

    # 保存裁切后的图片
    cropped_img.save(f"./data/{id}/image.png")
    os.remove(tmp_file)
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
        await page.screenshot(
            type="png",
            full_page=True,
            path=output_path,
            animations="disabled",
        )
        await browser.close()
