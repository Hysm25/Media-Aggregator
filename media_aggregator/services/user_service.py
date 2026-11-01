"""User access control and settings service."""

from __future__ import annotations

import asyncio
from typing import List, Optional
from media_aggregator.models import UserRecord, UserSettings
from media_aggregator.storage import StorageManager


class UserService:
    """Manages user registration, permissions, and preference persistence."""

    def __init__(self, storage: Optional[StorageManager] = None):
        self.storage = storage or StorageManager()

    async def get_or_create_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> UserRecord:
        """Fetch or initialize a user profile."""
        def _get_or_create() -> UserRecord:
            # If no users/admins exist in system, first user is not automatically admin until setup
            return self.storage.get_or_create_user(
                user_id=user_id,
                username=username,
                full_name=full_name,
                is_admin=False,
                is_allowed=False,
            )

        return await asyncio.to_thread(_get_or_create)

    async def is_authorized(self, user_id: int) -> bool:
        """Check whether user has granted access."""
        def _check() -> bool:
            user = self.storage.get_user(user_id)
            if not user:
                return False
            return user.is_allowed or user.is_admin

        return await asyncio.to_thread(_check)

    async def is_admin(self, user_id: int) -> bool:
        """Check whether user is an administrator."""
        def _check() -> bool:
            user = self.storage.get_user(user_id)
            return bool(user and user.is_admin)

        return await asyncio.to_thread(_check)

    async def has_admins(self) -> bool:
        """Check if any administrator is configured."""
        return await asyncio.to_thread(lambda: self.storage.count_admins() > 0)

    async def claim_first_admin(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> bool:
        """First-time setup: claim primary admin privileges if no admin exists."""
        def _claim() -> bool:
            if self.storage.count_admins() > 0:
                return False
            self.storage.get_or_create_user(
                user_id=user_id,
                username=username,
                full_name=full_name,
                is_admin=True,
                is_allowed=True,
            )
            self.storage.set_user_admin(user_id, True)
            self.storage.set_user_allowed(user_id, True)
            return True

        return await asyncio.to_thread(_claim)

    async def make_admin(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> bool:
        """Grant administrator and allowed privileges unconditionally."""
        def _make() -> bool:
            self.storage.get_or_create_user(
                user_id=user_id,
                username=username,
                full_name=full_name,
                is_admin=True,
                is_allowed=True,
            )
            self.storage.set_user_admin(user_id, True)
            self.storage.set_user_allowed(user_id, True)
            return True

        return await asyncio.to_thread(_make)

    async def get_user(self, user_id: int) -> Optional[UserRecord]:
        """Retrieve user details."""
        return await asyncio.to_thread(self.storage.get_user, user_id)

    async def update_settings(self, user_id: int, settings: UserSettings) -> None:
        """Update user preferences."""
        await asyncio.to_thread(self.storage.update_user_settings, user_id, settings)

    async def approve_user(self, user_id: int) -> bool:
        """Authorize a pending user."""
        return await asyncio.to_thread(self.storage.set_user_allowed, user_id, True)

    async def revoke_user(self, user_id: int) -> bool:
        """Revoke user access."""
        return await asyncio.to_thread(self.storage.set_user_allowed, user_id, False)

    async def list_users(self, allowed_only: bool = False) -> List[UserRecord]:
        """List all registered users."""
        return await asyncio.to_thread(self.storage.list_users, allowed_only)
