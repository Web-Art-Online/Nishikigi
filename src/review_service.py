from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable, Sequence

import config
from models import Article, Status
import utils


@dataclass(slots=True)
class ArticlePayload:
    id: int
    sender_id: int
    sender_name: str
    time: float
    anonymous: bool
    single: bool
    status: Status
    tid: str | None
    approve: str | None
    image_path: str | None

    @property
    def created_at(self) -> datetime:
        return datetime.fromtimestamp(self.time)


class ReviewCoordinator:
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    # 数据操作方法
    def list_articles(self, statuses: Sequence[Status] | None = None) -> list[Article]:
        query = Article.select().order_by(Article.id.asc())
        if statuses:
            query = query.where(Article.status << list(statuses))
        return list(query)

    def get_article(self, article_id: int) -> Article | None:
        return Article.get_or_none(Article.id == article_id)

    def article_payload(self, article: Article) -> ArticlePayload:
        image_path = None
        candidate = f"./data/{article.id}/image.png"
        if os.path.exists(candidate):
            image_path = candidate
        return ArticlePayload(
            id=article.id,
            sender_id=article.sender_id,
            sender_name=article.sender_name,
            time=article.time.timestamp() if hasattr(article.time, "timestamp") else float(article.time),
            anonymous=article.anonymous,
            single=article.single,
            status=article.status,
            tid=article.tid,
            approve=article.approve,
            image_path=image_path,
        )

    async def refresh_group_card(self) -> None:
        confirmed = Article.select().where(Article.status == Status.CONFRIMED)
        queue = Article.select().where(Article.status == Status.QUEUE)
        await self.bot.call_api(
            "set_group_card",
            {
                "group_id": config.GROUP,
                "user_id": self.bot.me.user_id,
                "card": f"待审核: {utils.to_list(confirmed)}\n待推送: {utils.to_list(queue)}",
            },
        )

    async def publish_articles(self, ids: Sequence[int | str]) -> list[str]:
        qzone = await self.bot.get_qzone()
        names = await qzone.upload_raw_image(
            album_name=config.ALBUM,
            file_path=list(map(lambda article_id: f"./data/{article_id}/image.png", ids)),
        )
        for i, article_id in enumerate(ids):
            Article.update({"tid": names[i], "status": Status.PUBLISHED}).where(
                Article.id == article_id
            ).execute()
            await self.bot.send_private(
                Article.get_by_id(article_id).sender_id,
                f"您的投稿 #{article_id} 已被推送😋",
            )
        await self.refresh_group_card()
        return names

    async def approve_articles(
        self, ids: Sequence[int | str], *, operator: int, is_emoji: bool = False
    ) -> None:
        flag = False
        for article_id in ids:
            article = Article.get_or_none(
                (Article.id == article_id) & (Article.status == Status.CONFRIMED)
            )
            if not article:
                if not is_emoji:
                    await self.bot.send_group(
                        group=config.GROUP, msg=f"投稿 #{article_id} 不存在或已通过审核"
                    )
                continue

            operators = article.approve.split(",") if article.approve else []
            if str(operator) in operators:
                continue
            operators.append(str(operator))

            Article.update({"approve": ",".join(operators)}).where(
                Article.id == article_id
            ).execute()

            if len(operators) <= 1:
                continue

            await self.bot.send_group(config.GROUP, f"投稿 #{article_id} 进入待发送队列")

            if article.single:
                await self.bot.send_group(group=config.GROUP, msg=f"开始推送 #{article_id}")
                await self.publish_articles([article_id])
                await self.bot.send_group(group=config.GROUP, msg=f"投稿 #{article_id} 已经单发")
                continue
            else:
                await self.bot.send_private(
                    article.sender_id,
                    f"您的投稿 {article} 已通过审核, 正在队列中等待发送",
                )
            flag = True
            Article.update(
                {
                    "status": Status.QUEUE,
                }
            ).where(Article.id == article_id).execute()

        if flag:
            articles = (
                Article.select()
                .where(Article.status == Status.QUEUE)
                .order_by(Article.id.asc())
                .limit(config.QUEUE)
            )
            if len(articles) < config.QUEUE:
                await self.bot.send_group(
                    group=config.GROUP, msg=f"当前队列中有{len(articles)}个稿件, 暂不推送"
                )
            else:
                await self.bot.send_group(
                    group=config.GROUP,
                    msg=f"队列已积压{len(articles)}个稿件, 将推送前{config.QUEUE}个稿件...",
                )
                tid = await self.publish_articles(list(map(lambda a: a.id, articles)))
                await self.bot.send_group(
                    group=config.GROUP,
                    msg=f"已推送{list(map(lambda a: a.id, articles))}\\ntid: {tid}",
                )

        await self.refresh_group_card()

    async def reject_article(self, article_id: int, operator: int, reason: str) -> bool:
        article = Article.get_or_none(
            (Article.id == article_id) & (Article.status == Status.CONFRIMED)
        )
        if article is None:
            return False

        Article.update({"status": Status.REJECTED, "approve": operator}).where(
            Article.id == article_id
        ).execute()
        await self.bot.send_private(
            article.sender_id,
            f"抱歉, 你的投稿 #{article_id} 已被管理员驳回😵‍💫 理由: {reason}",
        )
        await self.refresh_group_card()
        return True

    async def delete_articles(self, ids: Iterable[int]) -> list[int]:
        removed: list[int] = []
        for article_id in ids:
            article = Article.get_or_none(
                (Article.id == article_id) & (Article.status != Status.CREATED)
            )
            if not article:
                continue
            Article.delete_by_id(article_id)
            folder = f"./data/{article_id}"
            if os.path.exists(folder):
                shutil.rmtree(folder)

            if article.status == Status.PUBLISHED:
                qzone = await self.bot.get_qzone()
                album = await qzone.get_album(config.ALBUM)
                if album is None:
                    await self.bot.send_group(
                        config.GROUP, f"无法找到相册 {config.ALBUM}"
                    )
                else:
                    image = await qzone.get_image(album_id=album, name=article.tid)
                    if image is None:
                        await self.bot.send_group(
                            config.GROUP, f"无法找到投稿 #{article_id} 对应的空间动态图片"
                        )
                    else:
                        await qzone.delete_image(image)

            await self.bot.send_private(
                article.sender_id, f"你的投稿 #{article_id} 已被管理员删除😵‍💫"
            )
            removed.append(article_id)

        if removed:
            await self.refresh_group_card()
        return removed

    def serialize(self, payload: ArticlePayload, *, image_url: str | None) -> dict:
        data = asdict(payload)
        data["status"] = payload.status.value
        data["created_at"] = payload.created_at.isoformat()
        data["image_url"] = image_url
        return data


__all__ = ["ReviewCoordinator", "ArticlePayload"]
