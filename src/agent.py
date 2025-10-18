import base64
import json
import httpx
from botx.models import PrivateMessage

import config


def is_known_command(raw: str) -> bool:
    if not raw:
        return False
    s = raw.strip()

    # 仅识别以下完全匹配的命令
    valid_cmds = {
        "#投稿",
        "#投稿 匿名",
        "#投稿 单发",
        "#投稿 单发 匿名",
        "#结束",
        "#确认",
        "#取消",
        "#帮助",
        "#反馈",
        "＃投稿",
        "＃投稿 匿名",
        "＃投稿 单发",
        "＃投稿 单发 匿名",
        "＃结束",
        "＃确认",
        "＃取消",
        "＃帮助",
        "＃反馈",
    }
    # TODO 不要写死

    return s in valid_cmds


async def ai_suggest_intent(raw: str) -> dict:
    prompt = (
        "你是“苏州实验中学校墙”的智能助手, 任务是把用户短文本映射为墙的命令或友好回复。"
        '最终请返回 JSON: {"intent_candidates":[{"label":"","suggestion":"","confidence":"","reason":""}]}\n\n'
        f"墙的指令和说明:  \n"
        f"#帮助:  查看使用说明。\n"
        f"#投稿:  开启投稿模式。\n"
        f"投稿方式:  \n"
        f"#投稿 :  普通投稿(显示昵称, 由墙统一发布)\n"
        f"#投稿 单发 :  单独发一条空间动态\n"
        f"#投稿 匿名 :  匿名投稿(不显示昵称/头像)\n"
        f"#投稿 单发 匿名 :  匿名并单发\n"
        f"#结束:  结束当前投稿\n"
        f"#确认:  确认发送当前投稿\n"
        f"#取消:  取消投稿\n"
        f"#反馈:  向管理员反馈(示例:  #反馈 机器人发不出去)\n\n"
        f"原始消息: {raw}\n"
        "注意:  如果能直接给出建议命令(如 #投稿 匿名)请放在 suggestion 字段；"
        "如果只能给自然语言建议, 放在 reason 字段。请不要输出非 JSON 的内容。"
        "投稿方法是先发送命令, 然后按照提示操作, 不能直接投稿命令后面添加内容, 例如 #投稿 哈哈哈 是错误的! "
        "反馈就直接指令空格跟着反馈的内容就行, 例如 #反馈 哈哈哈 是正确的"
        "当用户发送没有什么意义的话, 直接返回帮助"
        "当用户发送 请求添加你为好友 或者类似的语句, 请给用户介绍自己, 并返回帮助"
        "如果用户发送了不正确的命令, 请告知用户如何修改为正确的指令, 必须要精确匹配才行"
        "用户发送的正确的命令不会由你处理, 所以你需要指正用户发的一切命令而不是回复完成"
    )

    headers = {
        "Authorization": f"Bearer {config.AGENT_ROUTER_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": config.AGENT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是把用户短文本转换成墙命令或友好建议的助手。输出 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 300,
        "temperature": 0.0,
    }

    resp_obj = {"intent_candidates": []}
    try:
        url = config.AGENT_ROUTER_BASE.rstrip("/") + "/v1/chat/completions"
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            j = r.json()
            text = ""
            if "choices" in j and len(j["choices"]) > 0:
                cand = j["choices"][0]
                if (
                    isinstance(cand, dict)
                    and "message" in cand
                    and isinstance(cand["message"], dict)
                ):
                    text = cand["message"].get("content", "") or ""
                else:
                    text = cand.get("text", "") or ""
            if not text and "text" in j:
                text = j.get("text", "")

            # 尝试解析 JSON
            try:
                parsed = json.loads(text)
                resp_obj = parsed
            except Exception:
                # 尝试提取文本中的 JSON 块
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    snippet = text[start : end + 1]
                    try:
                        parsed = json.loads(snippet)
                        resp_obj = parsed
                    except Exception:
                        resp_obj = {
                            "intent_candidates": [
                                {
                                    "label": "无法结构化解析",
                                    "suggestion": "",
                                    "confidence": "低",
                                    "reason": text[:400],
                                }
                            ]
                        }
                else:
                    resp_obj = {
                        "intent_candidates": [
                            {
                                "label": "无法结构化解析",
                                "suggestion": "",
                                "confidence": "低",
                                "reason": text[:400],
                            }
                        ]
                    }
    except Exception as e:
        from core import bot

        bot.getLogger().warning(f"AI call failed: {e}")
        resp_obj = {"intent_candidates": []}

    return resp_obj


async def summarize_image(image_path: str) -> str:
    """Generate a concise one-sentence summary describing the submission image."""

    headers = {
        "Authorization": f"Bearer {config.AGENT_ROUTER_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return ""

    prompt = (
        "你是校园墙的审核助理, 需要帮助管理员快速了解投稿图片的内容。"
        "请认真观察图片, 识别其中的文字、人物、物品、场景和主要事件。"
        "输出一条不超过 40 个汉字的中文概述, 用一句话覆盖最核心的信息。"
        "不要添加表情、标签、引导语, 不要臆测图片外的内容, 若有文字尽量提取关键词。"
    )

    body = {
        "model": config.AGENT_SUMMARY_MODEL,
        "max_tokens": 120,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请分析这张校园墙投稿图片并直接返回一句话概述。",
                    },
                    {
                        "type": "input_image",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
    }

    try:
        url = config.AGENT_ROUTER_BASE.rstrip("/") + "/v1/chat/completions"
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        from core import bot

        bot.getLogger().warning(f"AI summary call failed: {e}")
        return ""

    text = ""
    try:
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices:
            cand = choices[0]
            if isinstance(cand, dict):
                message = cand.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") in {"text", "output_text"}:
                                    text += item.get("text", "")
                elif "text" in cand:
                    text = cand.get("text", "")
            elif isinstance(cand, str):
                text = cand
        if not text and isinstance(data, dict):
            text = data.get("text", "")
    except Exception:
        text = ""

    summary = text.strip()
    summary = " ".join(summary.split())
    if len(summary) > 40:
        summary = summary[:40]

    return summary


async def reply_ai_suggestions(msg: PrivateMessage, ai_result: dict):
    candidates = (
        ai_result.get("intent_candidates", []) if isinstance(ai_result, dict) else []
    )

    if not candidates:
        await msg.reply(
            "抱歉, 我没理解你想做什么😵‍💫\n请尝试简短说明你的目标, 例如:  “我要匿名投稿”\n或者发送:  \n\n#帮助\n\n来查看操作指引\n\n若一直返回此提示可能是AI功能繁忙, 请稍等后重新发送"
        )
        return

    # 优先取有 suggestion 的候选
    best = next((c for c in candidates if c.get("suggestion")), None)

    if best:
        suggestion = best["suggestion"].strip()
        reason = best.get("reason", "").strip()

        msg_text = f"您可尝试发送:\n\n {suggestion}"
        if reason:
            msg_text += f"\n\n说明: {reason[:200]}"  # 保留更多信息
        msg_text += "\n\n直接发送命令即可执行, 或简要描述你的问题! (例如 我要投稿)"
        await msg.reply(msg_text)
    else:
        # 没有 suggestion, 则直接回复 reason
        reason_texts = [c.get("reason") for c in candidates if c.get("reason")]
        if reason_texts:
            await msg.reply(
                "🤖 建议:\n\n"
                + "\n\n".join(reason_texts)
                + "\n\n或简单描述您的需求, 我将为您提供建议! (例如 我要投稿)"
            )
        else:
            await msg.reply(
                "抱歉, 我无法生成命令😵‍💫\n请尝试简短描述你的需求或发送: \n\n#帮助\n\n查看操作指引\n\n若一直返回此提示可能是AI功能繁忙, 请稍等后重新发送"
            )
