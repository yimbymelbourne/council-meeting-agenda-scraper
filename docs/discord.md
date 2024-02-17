# Integrating and setting up Discord

To enable Discord functionality, you must do the following:

- Create a Discord application, and authenticate it for your server.
- Add valid `DISCORD_TOKEN` and `DISCORD_CHANNEL_ID` values to your `.env` file

## Create and authorise a Discord application

1. Create [a new Application](https://discord.com/developers/applications).

2. Go to Bot settings in the sidebar, and hit Reset Token.

3. Copy this token to `DISCORD_TOKEN` in your `.env`

4. Go to OAuth2 in the sidebar, then to URL Generator.

5. In Scopes, select `bot`

6. Then, in Bot Permissions, select `Send Messages`. **If you need to send messages in a private rather than public channel, you will need to select `Administrator`.**

7. Copy the Generated URL at the bottom of the page.

8. Paste that URL into the search bar, and follow the instructions to authorise the bot for your server.

## Get your channel id

1. To get your discord channel id, you need to write the server tag (e.g. `#scraper-test`) into Discord chat, and ensure it's showing up as tagged (i.e. highlighted in purple).

2. Next, place a backslash in front of the tag (e.g. `\#scraper-test` ) and hit send.

3. Your message should show up in the following format: `<#1203XXXXXXXXX709>`

4. Copy just the integer. This is your `DISCORD_CHANNEL_ID` value.

5. Add this value to your `.env` file

---

Your Discord bot should now function!
