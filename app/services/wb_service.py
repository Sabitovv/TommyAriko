import logging
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.entities import Product
from app.repositories.core import StoreRepository

logger = logging.getLogger(__name__)


class WBService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def sync_products(self) -> int:
        upserted = 0
        store_repo = StoreRepository(self.db)

        async with httpx.AsyncClient(timeout=30) as client:
            for store in self.settings.wb_stores:
                token = store["token"]
                store_id = store["store_id"]
                if not token or token == "replace_me":
                    logger.warning("wb_token_skipped", extra={"store": store_id})
                    continue

                db_store = await store_repo.get_or_create(store_id, store_id)
                await self.db.execute(
                    update(Product)
                    .where(Product.store_id == db_store.id)
                    .values(is_active=False)
                )

                headers = {"Authorization": token}
                items = await self._fetch_store_cards(client, headers, store_id)
                for item in items:
                    article = str(item.get("nmID") or "").strip()
                    if not article:
                        continue

                    title = self._clean_name(item.get("title") or item.get("object") or "Товар")
                    category = (item.get("subjectName") or item.get("subject") or "Без категории").strip()
                    payload = {
                        "store_id": db_store.id,
                        "category": category,
                        "name": title,
                        "article": article,
                        "wb_link": f"https://www.wildberries.ru/catalog/{article}/detail.aspx",
                        "warranty_months": 12,
                        "is_active": True,
                    }
                    stmt = insert(Product).values(**payload)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_article_store",
                        set_={
                            "category": payload["category"],
                            "name": payload["name"],
                            "wb_link": payload["wb_link"],
                            "warranty_months": payload["warranty_months"],
                            "is_active": True,
                        },
                    )
                    await self.db.execute(stmt)
                    upserted += 1

        await self.db.commit()
        return upserted

    async def _fetch_store_cards(self, client: httpx.AsyncClient, headers: dict[str, str], store_id: str) -> list[dict[str, Any]]:
        cursor: dict[str, Any] = {"limit": 100}
        cards: list[dict[str, Any]] = []
        while True:
            body = {
                "settings": {
                    "cursor": cursor,
                    "filter": {"withPhoto": -1},
                }
            }
            response = await client.post(
                "https://content-api.wildberries.ru/content/v2/get/cards/list",
                headers=headers,
                json=body,
            )
            if response.status_code != 200:
                logger.warning("wb_sync_failed", extra={"store": store_id, "status": response.status_code, "body": response.text[:300]})
                break

            data = response.json()
            batch = data.get("cards", [])
            cards.extend(batch)
            next_cursor = data.get("cursor") or {}
            if not batch or len(batch) < cursor["limit"]:
                break
            if not next_cursor.get("updatedAt") or next_cursor.get("nmID") is None:
                break
            cursor = {
                "limit": 100,
                "updatedAt": next_cursor["updatedAt"],
                "nmID": next_cursor["nmID"],
            }
        return cards

    @staticmethod
    def _clean_name(value: str) -> str:
        return " ".join(value.split()).strip()

    async def deduplicate_products(self, products: list[Product]) -> list[Product]:
        unique: dict[str, Product] = {}
        for p in products:
            key = p.name.lower().strip()
            unique.setdefault(key, p)
        return list(unique.values())

    async def get_products_for_keyboard(self) -> list[dict]:
        products = (
            await self.db.scalars(
                select(Product)
                .where(Product.is_active.is_(True))
                .order_by(Product.category, Product.name)
            )
        ).all()
        dedup = await self.deduplicate_products(products)
        return [{"id": p.id, "name": f"{p.category}: {p.name}"} for p in dedup]
