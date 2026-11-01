"""Tests for user management, authentication, and multi-user isolation."""

import pytest
from media_aggregator.models import (
    DownloadStatus,
    MediaItem,
    MediaType,
    SourceType,
    UserSettings,
)
from media_aggregator.services.user_service import UserService
from media_aggregator.storage import StorageManager


@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_user_data.db"
    return StorageManager(db_path=db_file)


@pytest.fixture
def user_service(temp_storage):
    return UserService(storage=temp_storage)


@pytest.mark.asyncio
async def test_user_registration_and_retrieval(user_service):
    user = await user_service.get_or_create_user(
        user_id=123456,
        username="alice",
        full_name="Alice Smith",
    )
    assert user.user_id == 123456
    assert user.username == "alice"
    assert user.is_admin is False
    assert user.is_allowed is False

    retrieved = await user_service.get_user(123456)
    assert retrieved is not None
    assert retrieved.full_name == "Alice Smith"


@pytest.mark.asyncio
async def test_claim_first_admin(user_service):
    assert await user_service.has_admins() is False

    # First user claims admin
    claimed = await user_service.claim_first_admin(111, username="admin1", full_name="Admin One")
    assert claimed is True
    assert await user_service.has_admins() is True
    assert await user_service.is_admin(111) is True
    assert await user_service.is_authorized(111) is True

    # Second user cannot claim admin through first-time wizard
    claimed_second = await user_service.claim_first_admin(222, username="user2", full_name="User Two")
    assert claimed_second is False
    assert await user_service.is_admin(222) is False


@pytest.mark.asyncio
async def test_user_authorization_lifecycle(user_service):
    await user_service.get_or_create_user(555, username="bob")
    assert await user_service.is_authorized(555) is False

    # Approve bob
    approved = await user_service.approve_user(555)
    assert approved is True
    assert await user_service.is_authorized(555) is True

    # Revoke bob
    revoked = await user_service.revoke_user(555)
    assert revoked is True
    assert await user_service.is_authorized(555) is False


@pytest.mark.asyncio
async def test_user_settings_update(user_service):
    user = await user_service.get_or_create_user(777, username="carol")
    assert user.settings.preferred_quality == "1080p"
    assert user.settings.exclude_cam is True

    new_settings = UserSettings(
        preferred_quality="4K",
        min_seeders=10,
        exclude_cam=False,
    )
    await user_service.update_settings(777, new_settings)

    updated = await user_service.get_user(777)
    assert updated.settings.preferred_quality == "4K"
    assert updated.settings.min_seeders == 10
    assert updated.settings.exclude_cam is False


@pytest.mark.asyncio
async def test_multi_user_isolation(temp_storage):
    # User 1 creates a download
    dl1 = temp_storage.create_download(
        media_id="tt001",
        media_title="Movie 1",
        source_type=SourceType.HTTP,
        target_url="http://example.com/1.mp4",
        user_id=1001,
    )
    # User 2 creates a download
    dl2 = temp_storage.create_download(
        media_id="tt002",
        media_title="Movie 2",
        source_type=SourceType.HTTP,
        target_url="http://example.com/2.mp4",
        user_id=1002,
    )

    # Scoped queries
    u1_dls = temp_storage.get_downloads(user_id=1001)
    u2_dls = temp_storage.get_downloads(user_id=1002)
    all_dls = temp_storage.get_downloads()

    assert len(u1_dls) == 1
    assert u1_dls[0].id == dl1
    assert len(u2_dls) == 1
    assert u2_dls[0].id == dl2
    assert len(all_dls) == 2

    # Bookmarks isolation
    item1 = MediaItem(id="tt101", title="Title A", type=MediaType.MOVIE)
    item2 = MediaItem(id="tt102", title="Title B", type=MediaType.MOVIE)
    temp_storage.add_bookmark(item1, user_id=1001)
    temp_storage.add_bookmark(item2, user_id=1002)

    bm1 = temp_storage.get_bookmarks(user_id=1001)
    bm2 = temp_storage.get_bookmarks(user_id=1002)
    assert len(bm1) == 1
    assert bm1[0]["media_id"] == "tt101"
    assert len(bm2) == 1
    assert bm2[0]["media_id"] == "tt102"
