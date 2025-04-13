import os
import dotenv
import dataclasses
import discord

from time import time
from typing import Optional
from discord import Guild, Role, Member, AllowedMentions, Interaction, app_commands
from discord.app_commands import Choice

from Enum.Constants import HELP_TROUBLESHOOTING_URLS
from Enum.HelpTopicEnum import HelpTopicEnum
from Enum.CommandEnum import CommandEnum
from Enum.PlatformEnum import PlatformEnum
from Class.UserApp import UserApp
from Class.LinkButtons import LinkButtons
from Utils.BotUtils import BotUtils
from Utils.InitDatabase import load_database

# Required permissions:
# - Manage Roles (required to set and remove roles from members)
# - Use Slash Commands (required to create and register commands in guilds)
# Invite link:
# https://discord.com/api/oauth2/authorize?client_id=1236022326773022800&permissions=2415919104&scope=bot%20applications.commands



# ------------------------------------- GLOBAL INITS
dotenv.load_dotenv()

database = load_database()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True

discord.utils.setup_logging()
discord.VoiceClient.warn_nacl = False  # doesn't need voice perms, it's a role assign bot
client = discord.Client(intents=intents)

tree = app_commands.CommandTree(client)

bot_utils = BotUtils(client, database, tree)



# ------------------------------------- EVENTS
# TODO properly remove roles from users when the bot is shut down
@client.event
async def on_ready():
    for guild in client.guilds:
        await bot_utils.setup_guild(guild)
    client.loop.create_task(bot_utils.update_apps_periodically())

@client.event
async def on_guild_join(guild: Guild):
    await bot_utils.setup_guild(guild)

@client.event
async def on_guild_remove(guild: Guild):
    if database.dexists("roles", str(guild.id)):
        database.dpop("roles", str(guild.id))

@client.event
async def on_presence_update(_: Member, member: Member):
    await bot_utils.check_member(member)

# Annoyingly required catch when member cannot be found by Discord else we get interaction timeout & ugly error
@tree.error
async def on_app_command_error(interaction: Interaction, error: app_commands.AppCommandError):
    global tree

    if interaction.command and interaction.command.name == CommandEnum.JOINED:
        if isinstance(error, app_commands.errors.TransformerError):
            await interaction.response.send_message(
                "❌ Could not find that member in the server.", ephemeral=True
            )
            return

    # Fallback to the original error handler to log all uncaught errors
    original_error_handler = tree.on_error
    await original_error_handler(interaction, error)

# Technically we should observe updates to roles
# that the listener roles depend on too but that happens so infrequently,
# we might as well wait until the presence has been updated.



# ------------------------------------- COMMANDS
@tree.command(name=CommandEnum.ROLE, description=CommandEnum.ROLE.description())
async def command_set_role(
    interaction: Interaction, for_role: Optional[Role], listener_role: Optional[Role], summary: Optional[bool],
):
    global database

    if interaction.guild_id is None:
        return await interaction.response.send_message("No guild ID for interaction")

    if not for_role and listener_role:
        return await interaction.response.send_message(
            "Need a role to set the listener role for"
        )

    is_reset = not listener_role
    guild_id = str(interaction.guild.id)
    if not database.dexists("roles", guild_id):
        if is_reset:
            return await interaction.response.send_message(
                "No listener roles configured"
            )
        database.dadd("roles", (guild_id, {}))

    if is_reset and not for_role:
        await bot_utils.remove_all_listener_roles_from_all(interaction.guild)
        database.dpop("roles", str(interaction.guild.id))
        return await interaction.response.send_message(
            "Removed all listener roles from all members"
        )

    guild_roles = database.dget("roles", guild_id)
    if is_reset and for_role:
        if str(for_role.id) in guild_roles:
            listener_role = await bot_utils.remove_listener_role_from_all(
                interaction.guild, for_role
            )
            listener_role_id = guild_roles[str(for_role.id)]
            assert listener_role is not None and listener_role.id == listener_role_id
            del guild_roles[str(for_role.id)]
            database.dadd("roles", (guild_id, guild_roles))
            return await interaction.response.send_message(
                f"Disabled monitoring for <@&{for_role.id}> "
                f"and removed the <@&{listener_role_id}> role from all members",
                allowed_mentions=AllowedMentions(roles=False),
            )
        else:
            return await interaction.response.send_message(
                f"No listener role configured for role <@&{for_role.id}>",
                allowed_mentions=AllowedMentions(roles=False),
            )

    if str(listener_role.id) in guild_roles:
        return await interaction.response.send_message(
            f"Cannot use <@&{listener_role.id}> as a listener role. "
            "It is already used as a requirement for a listener role",
            allowed_mentions=AllowedMentions(roles=False),
        )

    for other_listener_role_id in guild_roles.values():
        if for_role.id == other_listener_role_id:
            return await interaction.response.send_message(
                f"Cannot use <@&{for_role.id}> as a requirement for a listener role. "
                "It is already used as a listener role",
                allowed_mentions=AllowedMentions(roles=False),
            )

    if not listener_role.is_assignable():
        return await interaction.response.send_message(
            "Cannot assign this role to server members. "
            "Make sure the bot's role is above the specified role"
        )

    if not listener_role.permissions.is_subset(discord.Permissions.none()):
        return await interaction.response.send_message(
            "Only roles without any extra permissions are allowed"
        )

    guild_roles[str(for_role.id)] = listener_role.id
    database.dadd("roles", (guild_id, guild_roles))
    await bot_utils.check_guild(interaction.guild)
    await interaction.response.send_message(
        f"Listener role for <@&{for_role.id}> is now <@&{listener_role.id}>"
        + (f"\n{bot_utils.get_role_overview(interaction.guild)}" if summary else ""),
        allowed_mentions=AllowedMentions(roles=False),
    )

@tree.command(name=CommandEnum.ROLES, description=CommandEnum.ROLES.description())
async def command_list_roles(interaction: Interaction):
    if not database.dexists("roles", str(interaction.guild.id)):
        return await interaction.response.send_message(
            "No listener roles configured for this server"
        )

    overview = bot_utils.get_role_overview(interaction.guild)
    await interaction.response.send_message(
        overview,
        allowed_mentions=AllowedMentions(roles=False),
    )

@tree.command(name=CommandEnum.JOINED, description=CommandEnum.JOINED.description())
@app_commands.describe(member="The member to check (leave empty to check yourself)")
async def command_joined_stats(interaction: Interaction, member: Member = None):
    target_member = member or interaction.user
    guild = interaction.guild
    members_by_join_date = sorted(
        [member for member in guild.members if not member.bot],
        key=lambda m: m.joined_at or discord.utils.utcnow(),
    )

    try:
        member_index = members_by_join_date.index(target_member)
    except ValueError:
        await interaction.response.send_message(
            f"❌ Could not find {'yourself' if member is None else target_member.display_name} in the member list.",
            ephemeral=True,
        )
        return

    member_number = member_index + 1
    total_members = len(members_by_join_date)
    join_date = "Unknown"
    if target_member.joined_at:
        join_date = target_member.joined_at.strftime("%B %d, %Y")

    embed = discord.Embed(
        title="Member Timeline Position", color=0xE6DFD0  # Presence Beige:tm:
    )
    if member:
        embed.description = (
            f"**{target_member.display_name}** joined this server on **{join_date}**"
        )
        embed.add_field(
            name="Member Number",
            value=f"#{member_number} out of {total_members}",
            inline=False,
        )
    else:
        embed.description = f"You joined this server on **{join_date}**"
        embed.add_field(
            name="Your Member Number",
            value=f"#{member_number} out of {total_members}",
            inline=False,
        )

    if target_member.display_avatar:
        embed.set_thumbnail(url=target_member.display_avatar.url)

    percentage = 0
    if total_members > 1:
        percentage = round(((total_members - member_number) / (total_members - 1)) * 100, 1)

    embed.add_field(
        name="Early Bird Percentage",
        value=f"You joined earlier than {percentage}% of members",
        inline=True,
    )
    embed.set_footer(
        text=f"{guild.name} • Server created on {guild.created_at.strftime('%B %d, %Y')}"
    )

    await interaction.response.send_message(embed=embed)

@tree.command(name=CommandEnum.LISTENING, description=CommandEnum.LISTENING.description())
async def command_listening_role(interaction: Interaction, delete: Optional[bool]):
    guild_member = None
    for member in interaction.guild.members:
        if member.id == interaction.user.id:
            guild_member = member
            break

    if guild_member is None:
        return await interaction.response.send_message(
            "Interaction user not found amongst guild members"
        )

    user_id = guild_member.id
    if delete:
        database.dpop("user_apps", str(user_id))
        await bot_utils.check_member(guild_member)
        await interaction.response.send_message(
            f"Removed any registered app IDs for <@{user_id}>"
        )
        return

    count = 0
    for activity in guild_member.activities:
        if (
            not isinstance(activity, discord.Spotify)
            and isinstance(activity, discord.Activity)
            and activity.type == discord.ActivityType.listening
        ):
            app_id = activity.application_id
            if app_id is None:
                continue

            if database.dexists("apps", str(app_id)):
                await interaction.response.send_message(
                    f"App ID `{app_id}` is already known"
                )
                return

            if not database.dexists("user_apps", str(user_id)):
                database.dadd("user_apps", (str(user_id), {}))

            user_apps = database.dget("user_apps", str(user_id))
            # Only one custom app ID is allowed per user.
            user_apps.clear()
            user_apps[str(app_id)] = dataclasses.asdict(UserApp(app_id, guild_member.id, int(time())))
            database.dadd("user_apps", (str(user_id), user_apps))
            await interaction.response.send_message(
                f"Registered listening role for app ID `{app_id}` for <@{user_id}>"
            )
            count += 1

    if count == 0:
        return await interaction.response.send_message(
            f"No app ID found, make sure your presence is visible"
        )

    await bot_utils.check_member(guild_member)

@tree.command(name=CommandEnum.STOP, description=CommandEnum.STOP.description())
async def command_stop(interaction: Interaction):
    for guild in client.guilds:
        await bot_utils.remove_all_listener_roles_from_all(guild)

    await interaction.response.send_message("Removed all roles, stopping now")
    await client.close()

@tree.command(name=CommandEnum.LOGS, description=CommandEnum.LOGS.description())
@app_commands.choices(os=[
    Choice(name="Windows", value=PlatformEnum.WIN),
    Choice(name="Mac", value=PlatformEnum.MAC),
    Choice(name="Linux", value=PlatformEnum.LIN),
])
async def command_logs(interaction: Interaction, os: Choice[str] = None):
    await bot_utils.logs_response(interaction, os.value if os is not None else None)

@tree.command(name=CommandEnum.HELP, description=CommandEnum.HELP.description())
@app_commands.choices(topic=[
    Choice(name=HelpTopicEnum.INSTALL, value=HelpTopicEnum.INSTALL),
    Choice(name=HelpTopicEnum.PLAYER_DETECTION, value=HelpTopicEnum.PLAYER_DETECTION),
    Choice(name=HelpTopicEnum.APP_LOGS, value=HelpTopicEnum.APP_LOGS),
])
async def command_help(interaction: Interaction, topic: Choice[str] = None):
    value = HelpTopicEnum(topic.value) if topic is not None else None
    view = discord.utils.MISSING
    if value == HelpTopicEnum.INSTALL:
        try:
            view = LinkButtons(await bot_utils.get_download_urls())
        except Exception as e:
            return await interaction.response.send_message(f"An error occurred: {e}")

    elif value == HelpTopicEnum.PLAYER_DETECTION:
        view = LinkButtons(HELP_TROUBLESHOOTING_URLS)

    elif value == HelpTopicEnum.APP_LOGS:
        return await bot_utils.logs_response(interaction)

    await interaction.response.send_message(bot_utils.get_help_message(value), view=view)

client.run(os.getenv("BOT_TOKEN"))
