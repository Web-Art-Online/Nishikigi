import os
import dotenv

dotenv.load_dotenv()

# 审核群
GROUP = int(os.getenv("GROUP", "0"))

WS_URL = os.getenv("WS_URL", "ws://localhost:3001")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "")
NAME = os.getenv("NAME", "TestBot")
QUEUE = int(os.getenv("QUEUE", 6))

# 用于获取图片等的 FastAPI 服务
HOST = "localhost"
PORT = 8413

# 自定义状态的表情ID, 详见 https://github.com/NapNeko/NapCatQQ/blob/main/src/core/external/face_config.json
STATUS_ID = [400, 382, 383, 401, 400, 380, 381, 379, 376, 378, 377, 336]

AGENT_ROUTER_BASE = os.getenv("AGENT_ROUTER_BASE")
AGENT_ROUTER_KEY = os.getenv("AGENT_ROUTER_KEY")
