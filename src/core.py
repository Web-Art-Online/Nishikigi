import asyncio
import os
import shutil
import time
from typing import Sequence


import config
from models import Article, Session, Status
import image
import random
import traceback
import utils
import agent

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from uvicorn import Config, Server
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from botx import Bot
from botx.models import PrivateMessage, GroupMessage, User, PrivateRecall, FriendAdd
import httpx

bot = Bot(
    ws_uri=config.WS_URL, token=config.ACCESS_TOKEN, log_level="DEBUG", msg_cd=0.5
)

token = hex(random.randint(0, 2 << 128))[2:]

app = FastAPI()

# workers 必须为 1. 因为没有多进程数据同步.
server = Server(Config(app=app, host="localhost", port=config.PORT, workers=1))


def get_file_url(path: str):
    return f"http://{config.HOST}:{config.PORT}/image?p={path}&t={token}"


@app.get("/image")
def get_image(p: str, t: str):
    if t != token:
        raise HTTPException(status_code=401, detail="Nothing.")
    return FileResponse(path=p)


sessions: dict[User, Session] = {}

start_time = time.time()

# 管理的一些操作要上锁
lock = asyncio.Lock()

scheduler = AsyncIOScheduler()


@bot.on_error()
async def error(context: dict, data: dict):
    exc = context.get("exception")
    tb = "".join(traceback.format_exception(exc)) if exc is not None else "no traceback"
    if "user_id" in data:
        await bot.send_private(
            data["user_id"],
            f"出了一点小问题😵‍💫:\n\n{str(exc)}",
        )
        await bot.send_group(
            config.GROUP,
            f"和用户 {data['user_id']} 对话时出错:\n{tb}",
        )
    else:
        await bot.send_group(
            config.GROUP,
            f"出错了:\n{tb}",
        )


@bot.on_cmd(
    "投稿",
    help_msg=(
        f"我想来投个稿 😉\n\n"
        "—— 投稿方式 ——\n"
        " #投稿 :  普通投稿(显示昵称, 由墙统一发布)\n"
        " #投稿 单发 :  让墙单独发一条空间动态\n"
        " #投稿 匿名 :  隐藏投稿者身份\n"
        " #投稿 单发 匿名 :  匿名并单独发一条动态\n"
        "\n⚠️ 提示:  请正确输入命令, 不要多或少空格, 比如:  #投稿 匿名\n"
        f"\n示例见图:  [CQ:image,url={get_file_url('help/article.jpg')}]"
    ),
)
async def article(msg: PrivateMessage):
    raw = msg.raw_message.strip()

    # 定义严格允许的投稿命令
    valid_options = [
        "#投稿",
        "#投稿 单发",
        "#投稿 匿名",
        "#投稿 单发 匿名",
        "＃投稿",
        "＃投稿 单发",
        "＃投稿 匿名",
        "＃投稿 单发 匿名",
    ]

    # 如果命令不在允许列表中, 直接提示并返回
    if raw not in valid_options:
        await msg.reply(
            "❌ 投稿命令格式错误! \n"
            "正确格式示例:  \n"
            " #投稿\n"
            " #投稿 单发\n"
            " #投稿 匿名\n"
            " #投稿 单发 匿名\n"
            "请勿在命令后直接添加内容"
        )
        return

    anonymous = "匿名" in raw

    if msg.sender in sessions:
        await msg.reply("你还有投稿未结束🤔\n请先输入 #结束 来结束当前投稿")
        return

    parts = raw.split(" ")
    id = Article.create(
        sender_id=msg.sender.user_id,
        sender_name=msg.sender.nickname,
        anonymous=anonymous,
        time=time.time(),
        single="单发" in parts,
    ).id

    sessions[msg.sender] = Session(id=id, anonymous=anonymous)
    os.makedirs(f"./data/{id}", exist_ok=True)

    def status_words(value: bool) -> str:
        return "是" if value else "否"

    await msg.reply(
        f"✨ 开始投稿 😉\n"
        f"你发送的内容(除命令外)会计入投稿。\n"
        f"—— 投稿操作指南 ——\n"
        f"1️⃣ 完成投稿:  发送:  \n\n#结束\n\n来结束投稿并生成预览图\n"
        f"2️⃣ 取消投稿:  发送:  \n\n#取消\n\n来放弃本次投稿\n\n"
        f"匿名模式启用状态: {status_words(anonymous)}\n"
        f"单发模式启用状态: {status_words('单发' in parts)}\n"
        f"⚠️ 匿名和单发在设定后无法更改, 如需更改请先取消本次投稿"
    )

    if "单发" in parts:
        await msg.reply(
            "单发大概率被驳回! \n都单发的话, 大家的空间就会被挤满😵‍💫\n节约你我时间, 无需单发, 发送:  \n\n#取消\n\n后再重新投稿"
        )
    if anonymous:
        await msg.reply(
            "匿名投稿不显示你的昵称和头像\n若无需匿名,  发送:  \n\n#取消\n\n后再重新投稿\nPS: 之前有人匿名发失物招领"
        )

    await bot.send_group(config.GROUP, f"{msg.sender} 开始投稿")


@bot.on_cmd("结束", help_msg="用于结束当前投稿")
async def end(msg: PrivateMessage):
    if msg.sender not in sessions:
        await msg.reply("你还没有投稿哦~")
        return

    bot.getLogger().debug(sessions[msg.sender].contents)
    if not sessions[msg.sender].contents:
        await msg.reply(
            "你好像啥都没有说呢😵‍💫\n不想投稿了请输入:  \n\n#取消\n\n或者说点什么再输入:  \n\n#结束"
        )
        return
    await msg.reply("正在生成预览图🚀\n请稍等片刻")
    ses = sessions[msg.sender]

    for content in ses.contents:
        for m in content:
            if m["type"] == "image":
                filepath = f"./data/{ses.id}/{m['data']['file']}"
                if not os.path.isfile(filepath):
                    with httpx.stream(
                        "GET",
                        m["data"]["url"].replace("https://", "http://"),
                        timeout=60,
                    ) as resp:
                        with open(filepath, mode="bw") as file:
                            for chunk in resp.iter_bytes():
                                file.write(chunk)
                    bot.getLogger().info(f"下载图片: {filepath}")

    vips = (await bot.call_api("get_group_member_list", {"group_id": config.GROUP}))[
        "data"
    ]

    path = await image.generate_img(
        ses.id,
        user=msg.sender,
        contents=ses.contents,
        admin=any(map(lambda v: v["user_id"] == msg.sender.user_id, vips)),
        anonymous=ses.anonymous,
    )

    summary = await agent.summarize_image(path)
    summary_suffix = f"\n\nAI概述: {summary}" if summary else ""

    await msg.reply(
        f"[CQ:image,file={get_file_url(path)}]这样投稿可以吗😘\n可以的话请发送:  \n\n#确认\n\n不可以就发送:  \n\n#取消"
        + summary_suffix
    )


@bot.on_cmd("确认", help_msg="用于确认发送当前投稿")
async def done(msg: PrivateMessage):
    if not msg.sender in sessions:
        await msg.reply("你都还没投稿确认啥🤨")
        return

    session = sessions[msg.sender]
    if not os.path.isfile(f"./data/{session.id}/image.png"):
        await msg.reply("请先发送:  \n\n#结束\n\n来查看效果图🤔")
        return
    sessions.pop(msg.sender)
    Article.update({"status": Status.CONFRIMED}).where(
        Article.id == session.id
    ).execute()
    article = Article.get_by_id(session.id)
    anon_text = "匿名" if article.anonymous else ""
    single_text = ", 要求单发" if article.single else ""
    image_url = get_file_url(f"./data/{session.id}/image.png")
    await bot.send_group(
        config.GROUP,
        f"#{session.id} 用户 {msg.sender} {anon_text}投稿{single_text}\n[CQ:image,file={image_url}]",
    )

    await msg.reply("已成功投稿, 请耐心等待管理员审核😘")

    await bot.call_api(
        "set_diy_online_status",
        {
            "face_id": random.choice(config.STATUS_ID),
            "wording": f"已发 {len(Article.select().where(Article.status == Status.PUBLISHED))} 单",
        },
    )

    await update_name()


@bot.on_cmd("取消", help_msg="用于取消当前投稿")
async def cancel(msg: PrivateMessage):
    if not msg.sender in sessions:
        await msg.reply("你都还没投稿取消啥🤨")
        return

    id = sessions[msg.sender].id
    Article.delete_by_id(id)
    sessions.pop(msg.sender)
    shutil.rmtree(f"./data/{id}")
    await msg.reply("已取消本次投稿🫢")

    await bot.send_group(config.GROUP, f"{msg.sender} 取消了投稿")


@bot.on_cmd(
    "反馈",
    help_msg=f"用于向管理员反馈你的问题😘\n使用方法:  输入 #反馈 后直接加上你要反馈的内容\n本账号无人值守, 不使用反馈发送的消息无法被看到\n使用案例:  [CQ:image,file={get_file_url('help/feedback.png')}]",
)
async def feedback(msg: PrivateMessage):
    await bot.send_group(
        config.GROUP,
        f"用户 {msg.sender} 反馈:\n{msg.raw_message}",
    )
    await msg.reply("感谢你的反馈😘")


@bot.on_msg()
async def content(msg: PrivateMessage):
    raw = msg.raw_message or ""

    async def agent_reply(msg):
        await bot.call_api(
            "set_input_status", {"user_id": msg.sender.user_id, "event_type": 1}
        )
        ai_result = await agent.ai_suggest_intent(raw)
        await bot.call_api(
            "set_input_status", {"user_id": msg.sender.user_id, "event_type": 2}
        )
        await agent.reply_ai_suggestions(msg, ai_result)

    # 先处理投稿会话
    if msg.sender in sessions:
        # 如果是已知命令, 直接忽略, 不加入投稿内容
        if agent.is_known_command(raw):
            return  # 已知命令由 @bot.on_cmd 处理, 不加入投稿
        elif raw.startswith("#") or raw.startswith("＃"):
            await agent_reply(msg)
            return
        session = sessions[msg.sender]
        items = []
        for m in msg.message:
            m["id"] = msg.message_id
            if m["type"] not in ["image", "text", "face"]:
                await msg.reply(
                    "当前版本仅支持文字、图片、表情～\n如需发送其他类型, 请用 #反馈 告诉我们\n请不要使用QQ的回复/引用功能, 该功能无法被机器人理解"
                )
                await bot.send_group(
                    config.GROUP,
                    f"用户 {msg.sender} 发送了不支持的消息: {m.get('type')}",
                )
                continue
            items.append(m)
        if items:
            session.contents.append(items)
        return
    if agent.is_known_command(raw):
        return  # 已知命令由 @bot.on_cmd 处理, 不进入AI
    await agent_reply(msg)


@bot.on_notice()
async def recall(r: PrivateRecall):
    ses = sessions.get(User(nickname=None, user_id=r.user_id))  # type: ignore
    if not ses:
        return
    ses.contents = [c for c in ses.contents if c[0]["id"] != r.message_id]


# @bot.on_notice()
# async def friend(r: FriendAdd):
#     await bot.send_group(config.GROUP, f"{r.user_id} 添加了好友")


@bot.on_cmd(
    "通过",
    help_msg="通过投稿. 可以一次通过多条, 以空格分割. 如 #通过 1 2",
    targets=[config.GROUP],
)
async def accept(msg: GroupMessage):
    async with lock:
        parts = msg.raw_message.split(" ")
        if len(parts) < 2:
            await msg.reply("请带上要通过的投稿编号")
            return

        ids = parts[1:]
        flag = False  # 只有有投稿加入队列时才判断是否推送
        for id in ids:
            article = Article.get_or_none(
                (Article.id == id) & (Article.status == Status.CONFRIMED)
            )
            if not article:
                await msg.reply(f"投稿 #{id} 不存在或已通过审核")
                continue
            if article.single:
                await msg.reply(f"开始推送 #{id}")
                await publish([id])
                await msg.reply(f"投稿 #{id} 已经单发")
                continue
            else:
                await bot.send_private(
                    article.sender_id,
                    f"您的投稿 {article} 已通过审核, 正在队列中等待发送",
                )
            flag = True
            Article.update({Article.status: Status.QUEUE}).where(
                Article.id == id
            ).execute()

        if flag:
            articles = (
                Article.select()
                .where(Article.status == Status.QUEUE)
                .order_by(Article.id.asc())
                .limit(config.QUEUE)
            )
            if len(articles) < config.QUEUE:
                await msg.reply(f"当前队列中有{len(articles)}个稿件, 暂不推送")
            else:
                await msg.reply(
                    f"队列已积压{len(articles)}个稿件, 将推送前{config.QUEUE}个稿件..."
                )
                tid = await publish(list(map(lambda a: a.id, articles)))
                await msg.reply(
                    f"已推送{list(map(lambda a: a.id, articles))}\ntid: {tid}"
                )

        await update_name()


@bot.on_cmd(
    name="驳回",
    help_msg="驳回一条投稿, 需附带理由. 如 #驳回 1 不能引战",
    targets=[config.GROUP],
)
async def refuse(msg: GroupMessage):
    async with lock:
        parts = msg.raw_message.split(" ")
        if len(parts) < 3:
            await msg.reply("请带上要驳回的投稿和理由")
            return

        id = parts[1]
        reason = parts[2:]
        article = Article.get_or_none(
            (Article.id == id) & (Article.status == Status.CONFRIMED)
        )
        if article == None:
            await msg.reply(f"投稿 #{id} 不存在或已通过审核")
            return

        Article.update({"status": Status.REJECTED}).where(Article.id == id).execute()
        await bot.send_private(
            article.sender_id,
            f"抱歉, 你的投稿 #{id} 已被管理员驳回😵‍💫 理由: {' '.join(reason)}",
        )
        await msg.reply(f"已驳回投稿 #{id}")

        await update_name()


@bot.on_cmd(
    "推送",
    help_msg="推送指定的投稿, 可以推送多个. 如 #推送 1 2",
    targets=[config.GROUP],
)
async def push(msg: GroupMessage):
    async with lock:
        parts = msg.raw_message.split(" ")
        if len(parts) < 2:
            await msg.reply("请带上要通过的投稿id")
            return

        ids = parts[1:]
        for id in ids:
            article = Article.get_or_none(
                (Article.id == id) & (Article.status == Status.QUEUE)
            )
            if not article:
                await msg.reply(f"投稿 #{id} 不存在或已被推送或未通过审核")
                return
        await msg.reply(f"开始推送 {ids}")
        tid = await publish(ids)
        await msg.reply(f"已推送 {ids}\ntid: {tid}")
        await update_name()


@bot.on_cmd(
    "查看", help_msg="查看投稿, 可以查看多个, 如 #查看 1 2 3", targets=[config.GROUP]
)
async def view(msg: GroupMessage):
    parts = msg.raw_message.split(" ")
    if len(parts) < 2:
        await msg.reply("请带上要通过的投稿id")
        return

    ids = parts[1:]
    for id in ids:
        article = Article.get_or_none(Article.id == id)
        if not article or not os.path.exists(f"./data/{id}/image.png"):
            await msg.reply(f"投稿 #{id} 不存在")
            return

        match article.status:
            case Status.CREATED:
                status = "投稿中"
            case Status.CONFRIMED:
                status = "待审核"
            case Status.QUEUE:
                status = "待推送"
            case Status.REJECTED:
                status = "已驳回"
            case Status.PUBLISHED:
                status = "已推送"
            case _:
                status = "未知状态"

        anon_text = "匿名" if article.anonymous else ""
        single_text = ", 要求单发" if article.single else ""
        image_url = get_file_url(f"./data/{id}/image.png")

        await msg.reply(
            f"#{id} 用户 {article.sender_name}({article.sender_id}) {anon_text}投稿{single_text}\n"
            + f"[CQ:image,file={image_url}]\n"
            + f"状态: {status}",
        )


@bot.on_cmd("状态", help_msg="查看队列状态", targets=[config.GROUP])
async def status(msg: GroupMessage):
    confirmed = Article.select().where(Article.status == Status.CONFRIMED)
    queue = Article.select().where(Article.status == Status.QUEUE)
    await msg.reply(
        f"Nishikigi 已运行 {int(time.time() - start_time)}s\n待审核: {utils.to_list(confirmed)}\n待推送: {utils.to_list(queue)}"
    )


@bot.on_cmd("链接", help_msg="获取登录 QZone 的链接", targets=[config.GROUP])
async def link(msg: GroupMessage):
    clientkey = (await bot.call_api("get_clientkey"))["data"]["clientkey"]
    await msg.reply(
        f"http://ssl.ptlogin2.qq.com/jump?ptlang=1033&clientuin={bot.me.user_id}&clientkey={clientkey}"
        + f"&u1=https%3A%2F%2Fuser.qzone.qq.com%2F{bot.me.user_id}%2Finfocenter&keyindex=19"
    )


@bot.on_cmd(
    "回复",
    help_msg="回复用户. 如 #回复 10001 你是麻花疼吗? 你家的QQ真好用",
    targets=[config.GROUP],
)
async def reply(msg: GroupMessage):
    parts = msg.raw_message.split(" ")
    if len(parts) < 3:
        await msg.reply("请带上你想回复的人和内容")
        return
    try:
        int(parts[1])
    except:
        await msg.reply(f'"{parts[1]}" 不是一个有效的 QQ 号')
        return

    resp = await bot.send_private(
        int(parts[1]), f"😘管理员回复:\n{' '.join(parts[2:])}"
    )
    if resp is None:
        await msg.reply(f"无法回复用户 {parts[1]}\n请检查 QQ 号是否正确")
    else:
        await msg.reply(f"已回复用户 {parts[1]}")


async def publish(ids: Sequence[int | str]) -> str:
    qzone = await bot.get_qzone()
    text = ""
    images = []
    for id in ids:
        a = Article.get_by_id(id)
        text += (
            f"#{id}"
            + (f" " if a.anonymous else f" @{{uin:{a.sender_id},nick:null}}")
            + "\n"
        )
        images.append(
            await qzone.upload_image(utils.read_image(f"./data/{id}/image.png"))
        )
    tid = await qzone.publish(text, images=images)

    for id in ids:
        Article.update({"tid": tid, "status": Status.PUBLISHED}).where(
            Article.id == id
        ).execute()
        await bot.send_private(
            Article.get_by_id(id).sender_id, f"您的投稿 #{id} 已被推送😋"
        )
    return tid


async def update_name():
    confirmed = Article.select().where(Article.status == Status.CONFRIMED)
    queue = Article.select().where(Article.status == Status.QUEUE)
    await bot.call_api(
        "set_group_card",
        {
            "group_id": config.GROUP,
            "user_id": bot.me.user_id,
            "card": f"待审核: {utils.to_list(confirmed)}\n待推送: {utils.to_list(queue)}",
        },
    )


@scheduler.scheduled_job(IntervalTrigger(hours=1))
async def clear():
    async with lock:
        to_remove = []
        for sess in list(sessions.keys()):
            try:
                a = Article.get_by_id(sessions[sess].id)
            except Exception:
                continue
            time_passed = time.time() - a.time.timestamp()

            if time_passed > 60 * 60:
                to_remove.append(sess)
                Article.delete_by_id(a.id)
                if os.path.exists(f"./data/{a.id}"):
                    shutil.rmtree(f"./data/{a.id}")

                await bot.send_private(
                    sess.user_id, f"您的投稿 {a} 因为超时而被自动取消."
                )
                await bot.send_group(
                    config.GROUP, f"用户 {sess.user_id} 的投稿 {a} 因超时而被自动取消."
                )
                bot.getLogger().warning(f"取消用户 {sess.user_id} 的投稿 {a}")

        for sess in to_remove:
            sessions.pop(sess, None)


@bot.on_cmd(
    "删除", help_msg="删除一条投稿, 可以删除多条, 如 #删除 1 2", targets=[config.GROUP]
)
async def delete(msg: GroupMessage):
    async with lock:
        parts = msg.raw_message.split(" ")
        if len(parts) < 2:
            await msg.reply("请带上要删除的投稿id")
            return

        ids = parts[1:]
        for id in ids:
            article = Article.get_or_none(
                (Article.id == id) & (Article.status == Status.CONFRIMED)
            )
            if not article:
                await msg.reply(f"投稿 #{id} 不在队列中")
                return
            Article.delete_by_id(id)
            if os.path.exists(f"./data/{id}"):
                shutil.rmtree(f"./data/{id}")
            await bot.send_private(
                article.sender_id, f"你的投稿 #{id} 已被管理员删除😵‍💫"
            )

    await msg.reply(f"已删除 {ids}")
    await update_name()
