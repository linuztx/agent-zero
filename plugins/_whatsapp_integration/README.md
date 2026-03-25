# WhatsApp Integration

Communicate with Agent Zero through WhatsApp using neonize.

## What It Does

This plugin manages WhatsApp connections that receive and respond to messages. Each handler connects a WhatsApp account via QR code scanning. Messages are routed to Agent Zero contexts by chat JID.

It supports:

- **QR code authentication** displayed in the WebUI settings
- **All WhatsApp media types** (text, images, documents, audio, video, voice notes, stickers, locations, contacts)
- **Multiple accounts** with independent sessions

## Main Behavior

- **Client lifecycle**
  - Manages per-handler neonize clients that start/stop based on config changes.
  - Sessions persist in SQLite databases at `usr/whatsapp/sessions/`.
  - Auto-reconnects on restart without re-scanning QR.
- **Chat routing**
  - Maps each WhatsApp chat JID to one Agent Zero context.
  - /start creates a new context, /reset clears and recreates.
- **Media handling**
  - Downloads attachments into `usr/whatsapp/attachments`.
  - Supports sending file attachments in responses.
- **Access control**
  - Optional phone number whitelist per handler.
  - Configurable group chat support.

## Key Files

- **Core orchestration**
  - `helpers/handler.py` manages client lifecycle, message routing, and reply flow.
- **WhatsApp helpers**
  - `helpers/whatsapp_client.py` wraps neonize async API for sending/receiving.
- **API and extensions**
  - `api/` connects QR code display and connection testing.
  - `extensions/` hook into agent lifecycle for message handling.

## Configuration Scope

- **Settings section**: `external`
- **Per-project config**: `false`
- **Per-agent config**: `false`

## Plugin Metadata

- **Name**: `_whatsapp_integration`
- **Title**: `WhatsApp Integration`
- **Description**: Communicate with Agent Zero via WhatsApp using neonize. Supports QR code auth and multiple accounts.
