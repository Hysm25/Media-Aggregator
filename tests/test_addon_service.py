"""Tests for AddonService registration and manifest handling."""

from unittest.mock import MagicMock, patch
import pytest
from media_aggregator.services.addon_service import AddonService
from media_aggregator.storage import StorageManager


@pytest.fixture
def addon_service(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_addon_service.db")
    return AddonService(storage=storage)


@pytest.mark.asyncio
async def test_list_and_toggle_addon(addon_service):
    addons = await addon_service.list_addons()
    assert len(addons) >= 2  # Default Cinemeta and Torrentio

    cinemeta = next((a for a in addons if "cinemeta" in a.id.lower()), None)
    assert cinemeta is not None
    assert cinemeta.enabled is True

    # Toggle off
    toggled = await addon_service.toggle_addon(cinemeta.id, False)
    assert toggled is True

    updated_addons = await addon_service.list_addons()
    updated_cinemeta = next((a for a in updated_addons if a.id == cinemeta.id), None)
    assert updated_cinemeta.enabled is False


@pytest.mark.asyncio
async def test_add_addon_from_manifest(addon_service):
    mock_manifest = {
        "id": "community.test.addon",
        "name": "Community Stream Addon",
        "version": "1.0.0",
        "description": "Test description",
        "resources": ["stream"],
        "types": ["movie", "series"],
        "catalogs": [],
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_manifest
        mock_get.return_value = mock_resp

        success, msg, addon = await addon_service.add_addon_from_manifest_url("https://example.com/stremio/manifest.json")
        assert success is True
        assert addon is not None
        assert addon.id == "community.test.addon"
        assert addon.name == "Community Stream Addon"

        # Verify persisted
        addons = await addon_service.list_addons()
        saved = next((a for a in addons if a.id == "community.test.addon"), None)
        assert saved is not None
