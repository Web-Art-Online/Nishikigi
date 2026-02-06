import asyncio
import os

import core

if os.geteuid() == 0:
    print("请不要使用 root 用户运行此程序.")
    exit(-1)

os.makedirs("./data", exist_ok=True)
os.makedirs("./data/bg", exist_ok=True)


async def main():
    core.scheduler.start()
    await asyncio.gather(core.bot.start(), core.server.serve())


asyncio.run(main())
