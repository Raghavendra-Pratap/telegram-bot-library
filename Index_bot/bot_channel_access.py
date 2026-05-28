"""Whether Index Bot can publish (cards/files) in a Telegram channel."""

from __future__ import annotations

import logging

from telegram import ChatMemberAdministrator, ChatMemberOwner
from telegram.constants import ChatMemberStatus

logger = logging.getLogger(__name__)

# log_source values that imply the bot is in the chat and can post (after verify for add_channel).
BOT_POST_LOG_SOURCES = frozenset(
    {
        "channel_post",
        "my_chat_member",
        "add_channel",
        "discover_channels",
    }
)


async def verify_bot_can_post(bot, channel_id: str | int) -> bool:
    """True if the bot is channel admin/owner with permission to post messages."""
    try:
        member = await bot.get_chat_member(int(channel_id), bot.id)
    except Exception as exc:
        logger.debug("get_chat_member failed for %s: %s", channel_id, exc)
        return False

    if member.status == ChatMemberStatus.OWNER:
        return True
    if member.status != ChatMemberStatus.ADMINISTRATOR:
        return False
    if isinstance(member, ChatMemberOwner):
        return True
    if isinstance(member, ChatMemberAdministrator):
        # Restricted admins may lack post_messages; treat missing flag as allowed.
        can_post = member.can_post_messages
        return can_post is not False
    return True
