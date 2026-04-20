PLUGIN_NAME = "_discord_integration"
DOWNLOAD_FOLDER = "usr/uploads"
STATE_FILE = "usr/plugins/_discord_integration/state.json"

# Discord's per-message character cap for plain content
MAX_MESSAGE_LENGTH = 2000

# Discord attachment upload limit for bots without Nitro boost (bytes)
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

# Standard invite URL permissions bitfield:
# View Channels + Send Messages + Read History + Attach Files +
# Embed Links + External Emoji + Add Reactions
DEFAULT_INVITE_PERMISSIONS = 274878024704

# Context data keys
CTX_DC_BOT = "discord_bot"
CTX_DC_BOT_CFG = "discord_bot_cfg"
CTX_DC_CHANNEL_ID = "discord_channel_id"
CTX_DC_GUILD_ID = "discord_guild_id"
CTX_DC_USER_ID = "discord_user_id"
CTX_DC_USERNAME = "discord_username"
CTX_DC_TYPING_STOP = "_discord_typing_stop"
CTX_DC_REPLY_TO = "_discord_reply_to_message_id"

# Transient
CTX_DC_ATTACHMENTS = "_discord_response_attachments"
CTX_DC_KEYBOARD = "_discord_response_keyboard"
