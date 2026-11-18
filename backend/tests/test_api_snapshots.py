"""Tests for backup snapshot API (/api/v1/sync/snapshots).

Snapshot = ไฟล์สำรองของหน้าเว็บ (exportBackupJSON) เก็บทั้งก้อนแบบไม่แปลง
เพื่อให้กู้คืนกลับได้ครบทุกฟิลด์
"""
import copy

import pytest
from httpx import AsyncClient

from app.config import Settings, settings

URL = "/api/v1/sync/snapshots"


def frontend_backup(**overrides):
    """รูปแบบเดียวกับ exportBackupJSON() ใน script-pos.js"""
    data = {
        "products": [{"id": 1, "product_id": "8850001", "name": "น้ำดื่ม", "price": 10, "stock": 24}],
        "sales": [{"id": 1, "billNo": "B0001", "items": [{"product_id": "8850001", "qty": 2}], "total": 20}],
        "purchases": [],
        "debts": [{"id": 1, "customer": "ป้าแดง", "amount": 50, "paid": 0}],
        "expenses": [],
        "settings": {"shopName": "ร้านทดสอบ"},
        "holdBills": [],
        "billCounter": 2,
        "categoryMapping": [{"prefix": "885", "category": "เครื่องดื่ม"}],
        "hiddenMappingPrefixes": ["999"],
        "exportedAt": "2026-11-14T08:00:00.000Z",
        "version": 1,
    }
    data.update(overrides)
    return data


class TestSnapshotAPI:

    @pytest.mark.asyncio
    async def test_create_snapshot(self, client: AsyncClient):
        response = await client.post(URL, json=frontend_backup())

        assert response.status_code == 201
        body = response.json()
        assert body["created"] is True
        assert isinstance(body["id"], int)
        assert len(body["sha256"]) == 64
        assert body["size_bytes"] > 0
        assert body["counts"] == {"products": 1, "sales": 1, "debts": 1}

    @pytest.mark.asyncio
    async def test_same_data_is_not_stored_twice(self, client: AsyncClient):
        """ข้อมูลเหมือนเดิม (ต่างแค่ exportedAt) ต้องไม่เก็บซ้ำ"""
        first = (await client.post(URL, json=frontend_backup())).json()

        response = await client.post(URL, json=frontend_backup(exportedAt="2026-11-14T09:30:00.000Z"))

        assert response.status_code == 200
        body = response.json()
        assert body["created"] is False
        assert body["id"] == first["id"]
        assert len((await client.get(URL)).json()) == 1

    @pytest.mark.asyncio
    async def test_changed_data_creates_new_snapshot(self, client: AsyncClient):
        first = (await client.post(URL, json=frontend_backup())).json()

        response = await client.post(URL, json=frontend_backup(billCounter=3))

        assert response.status_code == 201
        assert response.json()["id"] != first["id"]

    @pytest.mark.asyncio
    async def test_latest_returns_exact_payload(self, client: AsyncClient):
        """กู้คืนต้องได้ข้อมูลเดิมทุกฟิลด์ รวมถึงฟิลด์ที่ backend ไม่รู้จัก"""
        await client.post(URL, json=frontend_backup())
        newest = frontend_backup(billCounter=9, extraField={"nested": [1, 2, 3]})
        await client.post(URL, json=newest)

        response = await client.get(f"{URL}/latest")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == newest
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_get_by_id(self, client: AsyncClient):
        created = (await client.post(URL, json=frontend_backup())).json()

        response = await client.get(f"{URL}/{created['id']}")

        assert response.status_code == 200
        assert response.json()["data"] == frontend_backup()

    @pytest.mark.asyncio
    async def test_get_unknown_id_is_404(self, client: AsyncClient):
        response = await client.get(f"{URL}/9999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_latest_without_snapshots_is_404(self, client: AsyncClient):
        response = await client.get(f"{URL}/latest")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_labels_keep_stores_separate(self, client: AsyncClient):
        """หน้าเว็บมีหลายร้าน — label แยก snapshot ของแต่ละร้าน"""
        store1 = frontend_backup(settings={"shopName": "ร้าน 1"})
        store2 = frontend_backup(settings={"shopName": "ร้าน 2"})
        await client.post(URL, params={"label": "store-1"}, json=store1)
        await client.post(URL, params={"label": "store-2"}, json=store2)

        r1 = await client.get(f"{URL}/latest", params={"label": "store-1"})
        r2 = await client.get(f"{URL}/latest", params={"label": "store-2"})
        r3 = await client.get(f"{URL}/latest", params={"label": "store-3"})

        assert r1.json()["data"] == store1
        assert r2.json()["data"] == store2
        assert r3.status_code == 404
        listed = (await client.get(URL, params={"label": "store-1"})).json()
        assert [s["label"] for s in listed] == ["store-1"]

    @pytest.mark.asyncio
    async def test_same_data_in_two_labels_is_kept_in_both(self, client: AsyncClient):
        a = await client.post(URL, params={"label": "store-1"}, json=frontend_backup())
        b = await client.post(URL, params={"label": "store-2"}, json=frontend_backup())

        assert a.status_code == 201
        assert b.status_code == 201

    @pytest.mark.asyncio
    async def test_list_is_newest_first_without_payload(self, client: AsyncClient):
        ids = []
        for counter in (1, 2, 3):
            ids.append((await client.post(URL, json=frontend_backup(billCounter=counter))).json()["id"])

        response = await client.get(URL)

        assert response.status_code == 200
        listed = response.json()
        assert [s["id"] for s in listed] == list(reversed(ids))
        assert "data" not in listed[0]
        assert listed[0]["counts"]["products"] == 1

    @pytest.mark.asyncio
    async def test_old_snapshots_are_pruned(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "SNAPSHOT_KEEP", 3)
        ids = []
        for counter in range(5):
            ids.append((await client.post(URL, json=frontend_backup(billCounter=counter))).json()["id"])

        listed = (await client.get(URL)).json()

        assert [s["id"] for s in listed] == list(reversed(ids[-3:]))
        assert (await client.get(f"{URL}/{ids[0]}")).status_code == 404

    @pytest.mark.asyncio
    async def test_pruning_is_per_label(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "SNAPSHOT_KEEP", 2)
        await client.post(URL, params={"label": "store-2"}, json=frontend_backup())
        for counter in range(4):
            await client.post(URL, params={"label": "store-1"}, json=frontend_backup(billCounter=counter))

        assert len((await client.get(URL, params={"label": "store-1"})).json()) == 2
        assert len((await client.get(URL, params={"label": "store-2"})).json()) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [
        {},
        {"hello": "world"},
        {"products": "not-a-list"},
    ])
    async def test_rejects_payload_that_is_not_a_backup(self, client: AsyncClient, payload):
        response = await client.post(URL, json=payload)

        assert response.status_code == 400
        assert (await client.get(URL)).json() == []

    @pytest.mark.asyncio
    async def test_rejects_non_object_body(self, client: AsyncClient):
        response = await client.post(URL, json=[frontend_backup()])
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_too_large_payload(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "SNAPSHOT_MAX_BYTES", 200)

        response = await client.post(URL, json=frontend_backup())

        assert response.status_code == 413
        assert (await client.get(URL)).json() == []

    @pytest.mark.asyncio
    async def test_rejects_too_long_label(self, client: AsyncClient):
        response = await client.post(URL, params={"label": "x" * 101}, json=frontend_backup())
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_payload_is_not_mutated_by_hashing(self, client: AsyncClient):
        """exportedAt ไม่นับตอนเทียบข้อมูลซ้ำ แต่ต้องยังอยู่ในข้อมูลที่เก็บ"""
        payload = frontend_backup()
        original = copy.deepcopy(payload)
        created = (await client.post(URL, json=payload)).json()

        stored = (await client.get(f"{URL}/{created['id']}")).json()["data"]

        assert stored == original
        assert stored["exportedAt"] == original["exportedAt"]


class TestBrowserAccessFromGitHubPages:
    """หน้าเว็บบน GitHub Pages (https) ต้องเรียก backend บนมือถือ (127.0.0.1) ได้"""

    ORIGIN = "https://zetxero-ceo.github.io"

    @pytest.mark.asyncio
    async def test_preflight_allows_github_pages_and_private_network(self, client: AsyncClient):
        response = await client.options(URL, headers={
            "Origin": self.ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        })

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == self.ORIGIN
        assert response.headers["access-control-allow-private-network"] == "true"

    @pytest.mark.asyncio
    async def test_preflight_from_other_site_gets_no_private_network_grant(self, client: AsyncClient):
        response = await client.options(URL, headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        })

        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-private-network" not in response.headers

    @pytest.mark.asyncio
    async def test_simple_request_from_github_pages_gets_cors_header(self, client: AsyncClient):
        response = await client.get(URL, headers={"Origin": self.ORIGIN})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == self.ORIGIN


class TestSafeDefaults:

    def test_default_host_is_loopback_only(self):
        """ค่าเริ่มต้นต้องไม่เปิดให้เครื่องอื่นใน Wi-Fi เดียวกันเข้าถึง (AUTH ปิดเป็นค่าเริ่มต้น)"""
        assert Settings.model_fields["HOST"].default == "127.0.0.1"
