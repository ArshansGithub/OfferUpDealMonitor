# tasks_manager.py
import asyncio
import random
from discord.ext import tasks
from datetime import datetime
import traceback
from .api_client import NobleHTTPClient
from .db import update_task
from loguru import logger
import discord
import matplotlib.pyplot as plt, matplotlib.dates as mdates, io
import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
import matplotlib
import openai
import os

toCheck = ["zipcode", "query", "distance", "delivery_flags", "condition_list", "price_min", "price_max"]
toCheckVehicle = ["veh_year_min", "veh_year_max", "veh_mileage", "veh_transmission",
                  "veh_drivetrain", "veh_style", "veh_mpg", "vehicle_make"]
matplotlib.use('Agg')

client = openai.AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

def generate_price_history_plot_sync(title, data_points):
    # dates = [datetime.fromisoformat(entry[0].replace("Z", "+00:00")) for entry in data_points]
    # prices = [entry[1] for entry in data_points]
    print(data_points)
    dates = []
    prices = []
    for entry in data_points:
        for k,v in entry.items():
            if k == "price":
                prices.append(float(v))
            elif k == "timestamp":
                # "2025-04-13T20:36:27.415657"
                dates.append(datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%S.%f+00:00"))

    fig, ax = plt.subplots(figsize=(16, 8))

    ax.plot(dates, prices, marker='o', linestyle='-', color='#1f77b4', linewidth=2, markersize=8, markerfacecolor='#ff7f0e')

    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d, %Y'))
    fig.autofmt_xdate(rotation=45)

    ax.grid(visible=True, which='both', linestyle='--', linewidth=0.5)

    ax.set_xlabel("Date", fontsize=14, labelpad=10)
    ax.set_ylabel("Price (USD)", fontsize=14, labelpad=10)
    ax.set_title(title, fontsize=18, pad=30)

    plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.2)

    image_buffer = io.BytesIO()
    plt.savefig(image_buffer, format='png')
    image_buffer.seek(0)

    plt.close(fig)

    return image_buffer.getvalue()

async def generate_price_history_plot(title, data_points):
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, generate_price_history_plot_sync, title, data_points)

async def monitor_task_runner(task_data: dict, bot, task_doc_id: str):
    """
    Runs the monitoring logic for one task.
    """
    try:
        logger.info(f"Running monitor for task {task_data['task_id']}")
        # Notify user that the task is running
        channel_id = os.getenv("LOG_CHANNEL_ID")
        if channel_id:
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(f"Running task {task_data['task_id']}...")
        # search_params = [
        #     {"key": "DELIVERY_FLAGS", "value": task_data.get("delivery_flags", "s")},
        #     {"key": "QUERY_SOURCE", "value": "RECENTS"},
        #     {"key": "q", "value": task_data.get("query")},
        #     {"key": "zipcode", "value": task_data.get("zipcode")},
        #     {"key": "distance", "value": str(task_data.get("distance", 50))},
        # ]
        search_params = [{"key": "SORT", "value": "-posted"}]
        for key in toCheck:
            val = task_data.get(key)
            if val not in [None, "", 0]:
                if key == "delivery_flags":
                    val = val[:1].lower()
                    key = "DELIVERY_FLAGS"
                if key == "condition_list":
                    if val == "ALL":
                        continue
                if key == "query":
                    key = "q"
                search_params.append({"key": key, "value": str(val)})
        
        if task_data.get("is_vehicle_search"):
            for key in toCheckVehicle:
                val = task_data.get(key)
                if val not in [None, "", 0]:
                    search_params.append({"key": key, "value": str(val)})
        
        if task_data.get("is_vehicle_search"):
            for key in ["veh_year_min", "veh_year_max", "veh_mileage", "veh_transmission",
                        "veh_drivetrain", "veh_style", "veh_mpg", "vehicle_make"]:
                val = task_data.get(key)
                if val not in [None, "", 0]:
                    search_params.append({"key": key, "value": str(val)})
        http_client = NobleHTTPClient()
        listings = await http_client.search_listings(search_params)

        logger.info(f"Task {task_data['task_id']} fetched {len(listings)} listings.")

        # Update cache and detect deals with price history.
        new_deals = []
        cache = task_data.get("cache", {})
        for listing in listings:
            listing_id = listing.get("listingId")
            try:
                current_price = float(listing.get("price", 0))
            except (ValueError, TypeError):
                continue
            history = cache.get(listing_id, [])
            if not history:
                # New listing.
                history.append({"price": current_price, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                cache[listing_id] = history
                new_deals.append(listing)
                logger.info(f"New listing detected: {listing_id} with price {current_price}")
            else:
                last_price = history[-1]["price"]
                if current_price != last_price:
                    history.append({"price": current_price, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                    logger.info(f"Price change for {listing_id}: {last_price} -> {current_price}")
                    if current_price < last_price:
                        new_deals.append(listing)
        # Update task document.
        update_task(task_data["task_id"], {"cache": cache, "last_checked": datetime.datetime.now(datetime.timezone.utc).isoformat(), "error": ""})
        if new_deals:
            logger.info(f"Task {task_data['task_id']} detected {len(new_deals)} new deals.")
            await send_deal_notifications(bot, task_data["user_id"], new_deals, cache, task_data["task_id"])
    except Exception as e:
        error_msg = traceback.format_exc()
        update_task(task_data["task_id"], {"error": error_msg})
        logger.error(f"Error in task {task_data['task_id']}: {error_msg}")
        user = await bot.fetch_user(task_data["user_id"])
        await user.send(f"Error in monitoring task {task_data['task_id']}: {str(e)}. The task has been stopped. You can update or re-enable it using the update command.")
        raise e

def create_monitor_loop(task_data: dict, bot: discord.Bot):
    frequency = float(task_data.get("interval", 5))
    logger.info(f"Creating monitor loop for task {task_data['task_id']} with frequency {frequency} minutes.")

    @tasks.loop(minutes=frequency)
    async def monitor_loop():
        await monitor_task_runner(task_data, bot, task_data["task_id"])
    return monitor_loop

async def send_deal_notifications(bot: discord.Bot, user_id: int, deals: list, cache: dict, task_id: str = None):
    user = await bot.fetch_user(user_id)
    logger.info(f"Sending {len(deals)} deal notifications to user {user_id}.")
    print(deals[0])
    for deal in deals:
        # Get p rice history from database cache
        price_history = cache.get(deal.get("listingId"), "")

        image = await generate_price_history_plot(f"'{deal.get('title', 'Unknown Title')}' Price History", price_history)
        url = None
        if isinstance(image, bytes):
            filee = discord.File(io.BytesIO(image), filename="price_history.png")
            url = "attachment://price_history.png"
        else:
            url = "https://i0.wp.com/knightlife.paceacademy.org/knightlynews/files/2024/10/mail.jpeg?resize=504%2C854&ssl=1"
                        
        
        # embed = discord.Embed(
        #     title=f"New Deal: {deal.get('title', 'Deal')}",
        #     description=f"Price: ${deal.get('price', '?')}\nListing ID: {deal.get('listingId')}",
        #     color=discord.Color.green()
        # )
        # {'listingId': 'e2524517-60a1-3c08-a20f-8af1f22c1a8f', 'conditionText': None, 'flags': ['LOCAL_PICKUP'], 'image': {'height': 250, 'url': 'https://images.offerup.com/D856BYJEVQUSygNdDuQbxYIK7KY=/250x250/f0ea/f0eacf7060a64f0aba3dd18ecea5781c.jpg', 'width': 250, '__typename': 'ModularFeedImage'}, 'isFirmPrice': None, 'locationName': 'San Marcos, CA', 'price': '260', 'formattedPrice': '$260', 'formattedOriginalPrice': '', 'priceDropPercentage': None, 'title': 'iPhone 12', 'vehicleMiles': None, '__typename': 'ModularFeedListing'}
        
        # replace all None values with "Unknown"
        for key in ["conditionText", "locationName", "price", "title"]:
            if deal.get(key) is None:
                deal[key] = "Unknown"
        
        embed = discord.Embed(
            title=f"New Deal: {deal.get('title', 'Unknown Title')}",
            url=f"https://offerup.com/item/detail/{deal.get('listingId', 'Unknown')}",
            fields=[
                discord.EmbedField(name="Price", value=f"${deal.get('price', 'Unknown')}", inline=True),
                discord.EmbedField(name="Location", value=deal.get("locationName", "Unknown"), inline=True),
                # discord.EmbedField(name="Condition", value=deal.get("conditionText", "Unknown"), inline=True),
            ]
        )
        embed.set_image(url=url)
        embed.set_footer(text=f"Task ID: {task_id}")
        embed.color = discord.Color.green()
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_thumbnail(url=deal.get("image", {}).get("url", ""))
        embed.set_author(name="OfferUp Monitor", icon_url="https://example.com/icon.png")
        print(embed)
        view = DealNotificationView(deal, task_id)
        msg = await user.send(embed=embed, view=view, files=[filee])

class DealNotificationView(discord.ui.View):
    def __init__(self, deal: dict, task_id: str = None):
        super().__init__(timeout=None)
        self.deal = deal
        self.task_id = task_id
        logger.debug(f"Created DealNotificationView for {self.deal.get('listingId')}.")
        
        self.add_item(GradeDealButton(deal, task_id))

    @discord.ui.button(label="More Info", style=discord.ButtonStyle.primary)
    async def more_info(self, button: discord.ui.Button, interaction: discord.Interaction):
        logger.info(f"More Info requested for listing {self.deal.get('listingId')}.")
        http_client = NobleHTTPClient()
        details = await http_client.fetch_item_details(self.deal.get("listingId"))
        print(details)
        # {'id': '1766209660', 'listingId': 'a382cf7e-faca-34cf-b28d-c717855f8c78', 'additionalDetails': [], 'availabilityConfirmedAt': None, 'condition': 40, 'conditionDisplayText': 'Used (normal wear)', 'description': 'iPhone 14 \n\nFactory unlocked for any carrier\n128gb storage\n86% battery\nClean condition\n\nAsking $400 obo\nLow ballers will be ignored', 'details': [], 'fulfillmentDetails': {'buyItNowEnabled': False, 'canShipToBuyer': False, 'isFreeShipping': False, 'localPickupEnabled': True, 'shippingEnabled': False, 'shippingPrice': None, 'shippingType': 'LocalOnly', 'showBuyNow': False, '__typename': 'FullfilmentDetails'}, 'isFirmOnPrice': False, 'isLocal': True, 'isAutosPost': False, 'isSold': False, 'isUnlisted': False, 'isRemoved': False, 'lastEdited': None, 'listingCategory': {'id': 'a382cf7e-faca-34cf-b28d-c717855f8c78:1.2.1', 'categoryAttributeMap': [{'attributeName': 'connectivity', 'attributeUILabel': 'Connectivity', 'attributeValue': [], '__typename': 'CategoryAttributeMap'}, {'attributeName': 'color', 'attributeUILabel': 'Color', 'attributeValue': [], '__typename': 'CategoryAttributeMap'}, {'attributeName': 'model', 'attributeUILabel': 'Model', 'attributeValue': [], '__typename': 'CategoryAttributeMap'}, {'attributeName': 'carrierNetwork', 'attributeUILabel': 'Network', 'attributeValue': [], '__typename': 'CategoryAttributeMap'}, {'attributeName': 'brand', 'attributeUILabel': 'Brand', 'attributeValue': [], '__typename': 'CategoryAttributeMap'}], 'categoryV2': {'id': '1.2.1', 'l1Name': 'Electronics & Media', 'l2Name': 'Cell phones & Accessories', '__typename': 'CategoryV2'}, '__typename': 'ListingCategory'}, 'locationDetails': {'latitude': '33.153', 'locationName': 'Escondido, CA', 'longitude': '-117.018', 'zipcode': '92027', '__typename': 'LocationDetails'}, 'originalPrice': '400', 'owner': {'id': 52245453, 'profile': {'avatars': {'squareImage': 'https://d2fa3j67sd1nwo.cloudfront.net/images/default-avatar-small-v2.png', '__typename': 'UserProfileAvatars'}, 'businessInfo': None, 'clickToCallEnabled': False, 'dateJoined': '2018-11-18T02:46:32Z', 'isAutosDealer': False, 'isBusinessAccount': False, 'isSubPrimeDealer': False, 'isTruyouVerified': True, 'lastActive': '', 'name': 'Isaac', 'notActive': False, 'ratingSummary': {'average': 5, 'count': 62, '__typename': 'RatingSummary'}, 'reviews': None, 'sellerType': 'Consumer', 'websiteLink': None, 'profileFeatures': {'canClickToCall': False, 'canViewItemsFromThisSeller': False, 'canViewStoreInventory': False, '__typename': 'ProfileFeatures'}, '__typename': 'UserProfile'}, '__typename': 'User'}, 'ownerId': '52245453', 'photos': [{'uuid': '4e95ff9537b947ec8c17bbc55dc58ce8', 'detailFull': {'url': 'https://images.offerup.com/U5bvkJuy8o_KpmOtaDke0lUkCiY=/1170x1139/4e95/4e95ff9537b947ec8c17bbc55dc58ce8.jpg', 'width': 1170, 'height': 1139, '__typename': 'Image'}, 'detailSquare': {'uuid': 'a815d9f448e04ec484117d3642b8cdf4', 'height': 1139, 'url': 'https://images.offerup.com/M3KCx5M_8JUlLk4_eA9-6RPTEA0=/1139x1139/a815/a815d9f448e04ec484117d3642b8cdf4.jpg', 'width': 1139, '__typename': 'Image'}, '__typename': 'Photo'}, {'uuid': 'b8426a118022450b9b11e87676442d97', 'detailFull': {'url': 'https://images.offerup.com/AI7hogpwvV6PLMuLGPWkhoCvPM8=/1170x1152/b842/b8426a118022450b9b11e87676442d97.jpg', 'width': 1170, 'height': 1152, '__typename': 'Image'}, 'detailSquare': None, '__typename': 'Photo'}], 'postDate': '2025-04-12T02:15:47.638Z', 'price': '400', 'title': 'iPhone 14', 'vehicleAttributes': {'vehicleCityMpg': None, 'vehicleEpaCity': None, 'vehicleEpaHighway': None, 'vehicleExternalHistoryReport': None, 'vehicleFundamentals': [], 'vehicleHighwayMpg': None, 'vehicleMake': None, 'vehicleMiles': None, 'vehicleModel': None, 'vehicleVin': None, 'vehicleYear': None, '__typename': 'VehicleAttributes'}, '__typename': 'Listing', 'formattedOriginalPrice': '$400', 'formattedPrice': '$400', 'isOwnItem': False, 'priceDropPercentage': '', 'showOriginalPrice': False, 'isGoodDeal': False}
        
        for key in ["conditionDisplayText", "locationName", "price", "title", "postDate", "ownerId", "owner"]:
            if details.get(key) is None:
                details[key] = "Unknown"
                
        # If too many new lines in description, remove and just have 1 new line
        if details.get("description"):
            # Any amount of new lines in description, replace with 1 new line
            details["description"] = "\n".join(details["description"].splitlines())
        
        embed = discord.Embed(
            title=f"Details for {self.deal.get('title', 'Deal')}",
            fields=[
                discord.EmbedField(name="Price", value=f"${self.deal.get('price', '?')}", inline=True),
                discord.EmbedField(name="Location", value=self.deal.get("locationName", "Unknown"), inline=True),
                discord.EmbedField(name="Condition", value=self.deal.get("conditionDisplayText", "Unknown"), inline=True),
                discord.EmbedField(name="Description", value=details.get("description", "No description available"), inline=False),
                discord.EmbedField(name="Posted", value=details.get("postDate", "Unknown"), inline=True),
                discord.EmbedField(name="Seller", value=details.get("owner", {}).get("profile", {}).get("name", "Unknown"), inline=True),
                discord.EmbedField(name="Rating", value=details.get("owner", {}).get("profile", {}).get("ratingSummary", {}).get("average", "Unknown"), inline=True),
                discord.EmbedField(name="Profile", value=f"https://offerup.com/profile/{details.get('ownerId', 'Unknown')}/", inline=True),
                discord.EmbedField(name="Business", value=details.get("owner", {}).get("profile", {}).get("isBusinessAccount", "Unknown"), inline=True),
                
            ],
            color=random.choice([discord.Color.red(), discord.Color.green(), discord.Color.blue(), discord.Color.purple()]),
        )
        embed.set_image(url=details.get("photos", [{}])[0].get("detailFull", {}).get("url", ""))
        # embed.set_footer(text=f"Listing ID: {self.deal.get('listingId', 'Unknown')}")
        embed.set_footer(text=f"Task ID: {self.task_id}")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_thumbnail(url=details.get("owner", [{}]).get("profile", {}).get("avatars", {}).get("squareImage", ""))
        embed.set_author(name="OfferUp Monitor", icon_url="https://example.com/icon.png")
        
        await interaction.response.send_message(embed=embed)
        self.disable_all_items()
        await interaction.message.edit(view=self)

class GradeDealButton(discord.ui.Button):
        def __init__(self, deal: dict, task_id: str = None):
            super().__init__(label="Grade Deal", style=discord.ButtonStyle.secondary)
            self.deal = deal
            self.task_id = task_id

        async def callback(self, interaction: discord.Interaction):
            logger.info(f"Grade Deal requested for listing {self.deal.get('listingId')}.")
            http_client = NobleHTTPClient()
            # Fetch detailed data to include in the grading prompt.
            details = await http_client.fetch_item_details(self.deal.get("listingId"))

            # Compose a prompt for GPT.
            prompt = (
                f"Please grade the following OfferUp listing as a deal. "
                f"Title: {details.get('title', 'Unknown')}\n"
                f"Price: ${details.get('price', 'Unknown')}\n"
                f"Condition: {details.get('conditionDisplayText', 'Unknown')}\n"
                f"Description: {details.get('description', 'No description available')}\n"
                f"Additional Details: {details}\n\n"
                f"Based on the above, provide a rating from 1 (poor deal) to 10 (excellent deal) along with a short explanation."
            )
            print(prompt)
            # Call the GPT API asynchronously (assumes you have set up OPENAI_API_KEY in your environment)
            try:
                response = await client.responses.create(
                    model="gpt-4.1-nano",
                    instructions="You are too analyze deals on OfferUp and provide a grade on how good of a deal it is. Think about the price, condition, and other factors. Be honest and provide a grade from 1 to 10. Keep it short and simple. Do not say something like the final value depends on market conditions. Your entire purpose is to be the one judging the deal.",
                    input=prompt,
                    temperature=0.5,
                )
                grade_text = response.output_text
            except Exception as e:
                logger.error(f"Error calling GPT API: {e}")
                grade_text = "Unable to grade this deal at the moment."

            # Send the grade result to the user.
            grade_embed = discord.Embed(
                title="Deal Grade",
                description=f"Grade and Analysis:\n{grade_text}",
                color=discord.Color.green()
            )
            grade_embed.set_footer(text=f"Task ID: {self.task_id}")
            await interaction.response.send_message(embed=grade_embed)