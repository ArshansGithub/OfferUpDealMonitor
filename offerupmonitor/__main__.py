import discord
from discord.ext import commands
from .db import get_tasks_by_user, get_task, delete_task, update_task
from .Constants import Constants
from .task_setup import TaskSetupSession
from .tasks_manager import create_monitor_loop
from .pagination import PaginationView
from datetime import datetime
import json
from loguru import logger
from .db import tasks_collection

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(intents=intents)

offerupCommands = bot.create_group("monitor", "OfferUp commands")
active_monitor_loops = {}

@bot.event
async def on_ready():
    logger.info(f"Bot is ready and logged in as {bot.user}")
    await load()

async def load():
    tasks_list = list(tasks_collection.find({"enabled": True}))
    logger.info(f"Loading {len(tasks_list)} enabled tasks from database.")
    for task in tasks_list:
        await update_active_tasks(task, bot)
        logger.info(f"Task {task['task_id']} loaded and scheduled.")

async def update_active_tasks(task, bot):
    if task["task_id"] not in active_monitor_loops:
        monitor = create_monitor_loop(task, bot)
        monitor.start()
        active_monitor_loops[task["task_id"]] = monitor
        logger.info(f"Scheduled task {task['task_id']} for user {task['user_id']}.")
    else:
        logger.info(f"Task {task['task_id']} is already active.")

@offerupCommands.command(name="newtask", description="Create a new OfferUp monitor task")
async def newtask(interaction: discord.Interaction):
    logger.info(f"User {interaction.user.id} initiated new task setup.")
    view = discord.ui.View()
    button = discord.ui.Button(label="Start Task Setup", style=discord.ButtonStyle.primary, custom_id="start_task_setup")
    async def button_callback(inter: discord.Interaction):
        session = TaskSetupSession(inter, bot, load)
        await session.start()
    button.callback = button_callback
    view.add_item(button)
    embed = discord.Embed(
        title="OfferUp Monitor - New Task Setup",
        description="Click the button below to start setting up your new task.",
        color=Constants.BRAND_COLOR
    )
    embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    logger.info(f"New task setup initiated by user {interaction.user.id}")

@offerupCommands.command(name="tasks", description="View your active tasks")
async def tasks(interaction: discord.Interaction):
    tasks_list = get_tasks_by_user(interaction.user.id)
    if not tasks_list:
        await interaction.response.send_message("You have no active tasks.", ephemeral=True)
        logger.info(f"User {interaction.user.id} requested tasks; none found.")
        return

    def embed_builder(item, index, total):
        embed = discord.Embed(
            title=f"Task {item.get('task_id')} - {item.get('friendly_name')}",
            description=f"Query: {item.get('query')}\nZipcode: {item.get('zipcode')}\nLast checked: {item.get('last_checked')}",
            color=Constants.BRAND_COLOR
        )
        embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
        embed.set_author(name="OfferUp Monitor", icon_url=Constants.BRAND_ICON)
        return embed

    view = PaginationView(tasks_list, embed_builder)
    first_embed = embed_builder(tasks_list[0], 0, len(tasks_list))
    await interaction.response.send_message(embed=first_embed, view=view, ephemeral=True)
    logger.info(f"Displayed tasks for user {interaction.user.id}")

@offerupCommands.command(name="delete_task", description="Delete a task by its task ID")
async def delete_task_cmd(interaction: discord.Interaction, task_id: str):
    task = get_task(task_id)
    if not task or task.get("user_id") != interaction.user.id:
        await interaction.response.send_message("Task not found or you do not have permission to delete it.", ephemeral=True)
        logger.warning(f"User {interaction.user.id} attempted to delete invalid task {task_id}.")
        return
    if task_id in active_monitor_loops:
        active_monitor_loops[task_id].stop()
        del active_monitor_loops[task_id]
        logger.info(f"Stopped monitor loop for task {task_id} before deletion.")
    delete_task(task_id)
    await interaction.response.send_message(f"Task {task_id} has been deleted.", ephemeral=True)
    logger.info(f"User {interaction.user.id} deleted task {task_id}.")

@offerupCommands.command(name="update_task", description="Update a task's status (enable/disable) by its task ID")
async def update_task_cmd(interaction: discord.Interaction, task_id: str, status: str):
    task = get_task(task_id)
    if not task or task.get("user_id") != interaction.user.id:
        await interaction.response.send_message("Task not found or you do not have permission to update it.", ephemeral=True)
        logger.warning(f"User {interaction.user.id} attempted to update invalid task {task_id}.")
        return
    new_status = True if status.lower() == "enable" else False
    update_task(task_id, {"enabled": new_status})
    if new_status and task_id not in active_monitor_loops:
        monitor = create_monitor_loop(task, bot)
        monitor.start()
        active_monitor_loops[task_id] = monitor
        await interaction.response.send_message(f"Task {task_id} has been enabled and scheduled.", ephemeral=True)
        logger.info(f"Task {task_id} enabled for user {interaction.user.id}.")
    elif not new_status and task_id in active_monitor_loops:
        active_monitor_loops[task_id].stop()
        del active_monitor_loops[task_id]
        await interaction.response.send_message(f"Task {task_id} has been disabled.", ephemeral=True)
        logger.info(f"Task {task_id} disabled for user {interaction.user.id}.")
    else:
        await interaction.response.send_message(f"Task {task_id} status updated to {'enabled' if new_status else 'disabled'}.", ephemeral=True)
        logger.info(f"Task {task_id} status updated for user {interaction.user.id}.")

@offerupCommands.command(name="refresh_task", description="Manually refresh a task by its task ID")
async def refresh_task_cmd(interaction: discord.Interaction, task_id: str):
    task = get_task(task_id)
    if not task or task.get("user_id") != interaction.user.id:
        await interaction.response.send_message("Task not found or you do not have permission.", ephemeral=True)
        logger.warning(f"User {interaction.user.id} attempted to refresh invalid task {task_id}.")
        return
    from .tasks_manager import monitor_task_runner
    try:
        await monitor_task_runner(task, bot, task_id)
        await interaction.response.send_message(f"Task {task_id} has been manually refreshed.", ephemeral=True)
        logger.info(f"Task {task_id} manually refreshed by user {interaction.user.id}.")
    except Exception as e:
        await interaction.response.send_message(f"Error refreshing task: {str(e)}", ephemeral=True)
        logger.error(f"Error manually refreshing task {task_id}: {str(e)}")

    logger.error(f"Error manually refreshing task {task_id}: {str(e)}")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    bot.run(os.getenv("DISCORD_TOKEN"))
