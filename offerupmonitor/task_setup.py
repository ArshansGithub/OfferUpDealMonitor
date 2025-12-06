import discord
from discord.ext import commands
import random, string
from datetime import datetime
from .db import create_task
from loguru import logger

from .Constants import Constants

# Field definitions for general task fields.
GENERAL_FIELDS = [
    {"key": "friendly_name", "prompt": "Task name", "type": "input", "datatype": "str"},
    {"key": "zipcode", "prompt": "Zipcode", "type": "input", "datatype": "str"},
    {"key": "query", "prompt": "Search query", "type": "input", "datatype": "str"},
    {"key": "interval", "prompt": "Check frequency (in minutes)", "type": "input", "datatype": "int"},
    {"key": "delivery_flags", "prompt": "Delivery flags", "type": "option", "options": ["Shipping", "Pickup", "Both"]},
    {"key": "condition_list", "required": False, "prompt": "Item conditions", "type": "option", "options": ["NEW", "USED", "OPEN BOX", "RECONDITIONED", "FOR PARTS", "OTHER", "ALL"], "multiple": True, "datatype": "str"},
    {"key": "distance", "prompt": "Maximum search distance (miles)", "type": "input", "datatype": "int"},
    {"key": "price_min", "required": False, "prompt": "Minimum price", "type": "input", "datatype": "int"},
    {"key": "price_max", "required": False, "prompt": "Maximum price", "type": "input", "datatype": "int"},
    {"key": "is_vehicle_search", "prompt": "Is this search for a vehicle? (true/false)", "type": "boolean"},
    {"key": "notify_price_drop", "prompt": "Notify on price drop? (true/false)", "type": "boolean"}
]

# Field definitions for vehicle–specific parameters.
VEHICLE_FIELDS = [
    {"key": "veh_year_min", "required": False, "prompt": "Minimum vehicle year", "type": "input", "datatype": "int"},
    {"key": "veh_year_max", "required": False, "prompt": "Maximum vehicle year", "type": "input", "datatype": "int"},
    {"key": "veh_mileage", "required": False, "prompt": "Vehicle mileage", "type": "option",
     "options": ["Any", "25000", "50000", "75000", "100000", "125000", "150000", "175000", "200000"], "datatype": "int"},
    {"key": "veh_transmission", "required": False, "prompt": "Transmission", "type": "option", "options": ["Any", "m", "a"]},
    {"key": "veh_drivetrain", "required": False, "prompt": "Drivetrain", "type": "option", "options": ["Any", "a", "r", "f"]},
    {"key": "veh_style", "required": False, "prompt": "Vehicle style", "type": "option", "options": ["Any", "s", "t", "v", "c"]},
    {"key": "veh_mpg", "required": False, "prompt": "Minimum MPG", "type": "option", "options": ["Any", "10", "20", "30", "40"], "datatype": "int"},
    {"key": "vehicle_make", "required": False, "prompt": "Vehicle make", "type": "option", 
     "options": ["Any", "ab", "ac", "ad", "aj", "an", "ap",
                 "bb", "bf", "bi", "bj", "c", "cc", "cd", "d", "dc", "de", "dh",
                 "e", "fb", "fc", "fd", "fe", "ga", "ge", "hb", "he", "hf", "i", "ic",
                 "j", "jb", "k", "lb", "ld", "lf", "lg", "lh", "mb", "me", "mf", "mh",
                 "mi", "mk", "ml", "n", "o", "pe", "pf", "pg", "r", "re", "s", "sb",
                 "sc", "sh", "sl", "sn", "tc", "td", "vb", "vc"]}
]

def generate_task_id(length=6):
    task_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    logger.debug(f"Generated task_id: {task_id}")
    return task_id

# --- Helper: Safe send ---
async def safe_send(interaction: discord.Interaction, content=None, embed=None, view=None, ephemeral=True):
    if not interaction.response.is_done():
        await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)
    else:
        await interaction.edit_original_response(content=content, embed=embed, view=view)

# --- RetryButtonView ---
class RetryButtonView(discord.ui.View):
    def __init__(self, session, modal_creator):
        super().__init__(timeout=60)
        self.session = session
        self.modal_creator = modal_creator

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.danger)
    async def retry_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        logger.info("Retry button clicked, reopening modal.")
        self.stop()
        modal = self.modal_creator(self.session.current_modal_title, self.session.current_modal_fields, self.session)
        modal.interaction_on_submit = self.session.handle_input_modal_submission
        await interaction.response.send_modal(modal)

# --- NextButtonView ---
class NextButtonView(discord.ui.View):
    def __init__(self, session, func):
        super().__init__(timeout=60)
        self.func = func

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        logger.debug("Next button clicked.")
        self.stop()
        await self.func(interaction)

# --- MultiInputModal ---
class MultiInputModal(discord.ui.Modal):
    def __init__(self, title: str, fields: list, session: object):
        super().__init__(title=title, timeout=180)
        self.session = session  # Store reference to the TaskSetupSession.
        self.fields_info = fields
        for field in fields:
            self.add_item(discord.ui.InputText(
                label=field["prompt"],
                placeholder=field["prompt"],
                required=field.get("required", True)
            ))
    
    async def callback(self, interaction: discord.Interaction):
        results = {}
        errors = []
        for idx, field in enumerate(self.fields_info):
            raw_value = self.children[idx].value.strip()
            datatype = field.get("datatype", "str")
            try:
                if datatype == "int":
                    casted = int(raw_value) if raw_value != "" else None
                elif datatype == "float":
                    casted = float(raw_value) if raw_value != "" else None
                elif datatype == "bool":
                    if raw_value.lower() == "true":
                        casted = True
                    elif raw_value.lower() == "false":
                        casted = False
                    else:
                        raise ValueError
                else:
                    casted = raw_value
            except ValueError:
                errors.append(f"'{field['prompt']}' expects {datatype}.")
                continue
            results[field["key"]] = casted
        if errors:
            error_text = "\n".join(errors)
            error_embed = discord.Embed(
                title="Input Error",
                description=f"The following errors occurred:\n{error_text}",
                color=0xE74C3C
            )
            error_embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
            retry_view = RetryButtonView(self.session, lambda title, fields, session: MultiInputModal(title, fields, session))
            await safe_send(interaction, content="Click Retry to re-enter your inputs.", view=retry_view, embed=error_embed)
            return
        logger.info(f"MultiInputModal submission: {results}")
        await interaction.response.defer(ephemeral=True)
        await self.interaction_on_submit(interaction, results)

# --- PaginatedSelect (for long option lists) ---
class PaginatedSelect(discord.ui.Select):
    def __init__(self, field: dict, current_value, on_select_callback, current_page=0, page_size=20):
        self.field = field
        self.full_options = field["options"]
        self.current_page = current_page
        self.page_size = page_size
        self.on_select_callback = on_select_callback
        self.current_value = current_value
        if field.get("multiple", False):
            minv = 1
            maxv = len(self.full_options)
        else:
            minv = 1
            maxv = 1
        super().__init__(placeholder=field["prompt"], custom_id=f"paginated_{field['key']}",
                         min_values=minv, max_values=maxv)
        self.update_options()

    def update_options(self):
        start = self.current_page * self.page_size
        end = start + self.page_size
        current_slice = self.full_options[start:end]
        options = [discord.SelectOption(label=opt, value=opt) for opt in current_slice]
        if self.current_page > 0:
            options.insert(0, discord.SelectOption(label="‹‹ Previous Page", value="__prev__"))
        max_page = (len(self.full_options) - 1) // self.page_size
        if self.current_page < max_page:
            options.append(discord.SelectOption(label="Next Page ››", value="__next__"))
        self.options = options

    async def callback(self, interaction: discord.Interaction):
        if "__prev__" in self.values:
            self.current_page -= 1
            self.update_options()
            await interaction.response.edit_message(view=self.view)
            logger.info(f"Paginated select {self.field['key']} moved to previous page.")
        elif "__next__" in self.values:
            self.current_page += 1
            self.update_options()
            await interaction.response.edit_message(view=self.view)
            logger.info(f"Paginated select {self.field['key']} moved to next page.")
        else:
            self.current_value = self.values
            await self.on_select_callback(interaction, self.field["key"], self.values)
            logger.info(f"Paginated select {self.field['key']} set to {self.values}")

# --- BooleanOptionView ---
class BooleanOptionView(discord.ui.View):
    def __init__(self, boolean_fields: list, option_fields: list, initial_state: dict):
        super().__init__(timeout=180)
        self.boolean_fields = boolean_fields
        self.option_fields = option_fields
        self.state = initial_state.copy()
        for idx, field in enumerate(boolean_fields):
            btn = discord.ui.Button(
                label=f"{field['prompt']}: {self.state.get(field['key'], False)}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"bool_{field['key']}",
                row=idx
            )
            btn.callback = self.make_boolean_callback(field)
            self.add_item(btn)
        for idx, field in enumerate(option_fields):
            if len(field["options"]) > 25:
                select = PaginatedSelect(field, self.state.get(field["key"], field["options"][0]), self.make_option_callback(field))
                select.row = len(boolean_fields) + idx
                self.add_item(select)
            else:
                opts = [discord.SelectOption(label=o, value=o) for o in field["options"]]
                select = discord.ui.Select(
                    placeholder=field["prompt"],
                    options=opts,
                    custom_id=f"opt_{field['key']}",
                    row=len(boolean_fields) + idx
                )
                if field.get("multiple", False):
                    select.max_values = len(field["options"])
                else:
                    select.max_values = 1
                select.callback = self.make_option_callback(field)
                self.add_item(select)
        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success, custom_id="confirm_boolopt", row=len(boolean_fields) + len(option_fields))
        confirm.callback = self.confirm_callback
        self.add_item(confirm)

    def get_updated_embed(self):
        embed = discord.Embed(
            title="Boolean/Option Phase",
            description="Toggle booleans and select options below. Click Confirm when done.",
            color=Constants.BRAND_COLOR
        )
        embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
        for field in self.boolean_fields:
            embed.add_field(name=field["prompt"], value=str(self.state.get(field["key"], False)), inline=True)
        for field in self.option_fields:
            embed.add_field(name=field["prompt"], value=str(self.state.get(field["key"])), inline=True)
        return embed

    def make_boolean_callback(self, field):
        async def callback(interaction: discord.Interaction):
            current = self.state.get(field["key"], False)
            new_val = not current
            self.state[field["key"]] = new_val
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id == f"bool_{field['key']}":
                    child.label = f"{field['prompt']}: {new_val}"
                    break
            new_embed = self.get_updated_embed()
            await interaction.response.edit_message(embed=new_embed, view=self)
            logger.info(f"Boolean field {field['key']} toggled to {new_val}")
        return callback

    def make_option_callback(self, field):
        async def callback(interaction: discord.Interaction):
            selected = interaction.data.get("values")
            if selected:
                self.state[field["key"]] = selected[0]
            new_embed = self.get_updated_embed()
            await interaction.response.edit_message(embed=new_embed, view=self)
            logger.info(f"Option field {field['key']} set to {self.state[field['key']]}")
        return callback

    async def confirm_callback(self, interaction: discord.Interaction):
        logger.info("Boolean/option phase confirmed.")
        self.stop()
        if hasattr(self, "interaction_on_confirm"):
            await self.interaction_on_confirm(interaction, self.state)

# --- TaskSetupSession ---
class TaskSetupSession:
    def __init__(self, interaction: discord.Interaction, bot: discord.Bot, reload_func=lambda: print("Reload function not set")):
        self.bot = bot
        self.reload_func = reload_func
        self.interaction = interaction
        self.data = {}
        self.data["task_id"] = generate_task_id()
        self.data["user_id"] = interaction.user.id
        self.input_fields = [f for f in GENERAL_FIELDS if f["type"] == "input"]
        self.bool_fields = [f for f in GENERAL_FIELDS if f["type"] == "boolean"]
        self.option_fields = [f for f in GENERAL_FIELDS if f["type"] == "option"]
        self.input_batches = [self.input_fields[i:i+5] for i in range(0, len(self.input_fields), 5)]
        self.current_batch_index = 0
        self.boolopt_state = {}
        for field in self.bool_fields:
            self.boolopt_state[field["key"]] = False
        for field in self.option_fields:
            self.boolopt_state[field["key"]] = field.get("options", [None])[0]
        self.vehicle_phase = False
        # These attributes are used to re-open a modal if needed.
        self.current_modal_title = None
        self.current_modal_fields = None
        logger.info(f"TaskSetupSession started for user {interaction.user.id} with task_id {self.data['task_id']}.")

    async def start(self):
        logger.info("Starting input phase for task setup session.")
        await self.ask_next_input_modal(self.interaction)

    async def ask_next_input_modal(self, interaction: discord.Interaction):
        if self.current_batch_index < len(self.input_batches):
            batch = self.input_batches[self.current_batch_index]
            title = f"Input Batch {self.current_batch_index + 1}/{len(self.input_batches)}"
            self.current_modal_title = title
            self.current_modal_fields = batch
            modal = MultiInputModal(title, [{**field, "required": field.get("required", True)} for field in batch], self)
            modal.interaction_on_submit = self.handle_input_modal_submission
            await interaction.response.send_modal(modal)
        else:
            await self.start_boolopt_phase(interaction)

    async def handle_input_modal_submission(self, interaction: discord.Interaction, results: dict):
        self.data.update(results)
        logger.info(f"Input modal batch submitted: {results}")
        self.current_batch_index += 1
        if self.current_batch_index < len(self.input_batches):
            view = NextButtonView(self, self.ask_next_input_modal)
            await safe_send(interaction, content="Proceed to next input batch?", view=view)
        else:
            view = NextButtonView(self, self.start_boolopt_phase)
            await safe_send(interaction, content="Input phase complete. Proceed to adjust booleans/options?", view=view)

    async def start_boolopt_phase(self, interaction: discord.Interaction):
        logger.info("Starting boolean/option phase.")
        embed = discord.Embed(
            title="Boolean/Option Phase",
            description="Toggle booleans and select options below. Click Confirm when done.",
            color=Constants.BRAND_COLOR
        )
        embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
        for field in self.bool_fields:
            embed.add_field(name=field["prompt"], value=str(self.boolopt_state.get(field["key"])), inline=True)
        for field in self.option_fields:
            embed.add_field(name=field["prompt"], value=str(self.boolopt_state.get(field["key"])), inline=True)
        view = BooleanOptionView(self.bool_fields, self.option_fields, self.boolopt_state)
        async def on_confirm(interaction: discord.Interaction, new_state: dict):
            self.boolopt_state = new_state
            self.data.update(new_state)
            is_vehicle = self.data.get("is_vehicle_search")
            if isinstance(is_vehicle, str):
                is_vehicle = is_vehicle.lower() == "true"
            if is_vehicle:
                logger.info("Vehicle search enabled; sending button to start vehicle phase.")
                btn_view = discord.ui.View()
                vehicle_btn = discord.ui.Button(
                    label="Start Vehicle Phase",
                    style=discord.ButtonStyle.primary,
                    custom_id="start_vehicle_phase_vehicle"
                )
                async def vehicle_callback(interaction: discord.Interaction):
                    await self.start_vehicle_phase(interaction)
                vehicle_btn.callback = vehicle_callback
                btn_view.add_item(vehicle_btn)
                await safe_send(interaction, content="Click the button to start vehicle phase.", view=btn_view)
            else:
                await self.finish_setup(interaction)
        view.interaction_on_confirm = on_confirm
        await safe_send(interaction, embed=embed, view=view)

    async def start_vehicle_phase(self, interaction: discord.Interaction):
        vehicle_input = [f for f in VEHICLE_FIELDS if f["type"] == "input"]
        if vehicle_input:
            modal = MultiInputModal("Vehicle Input Phase", vehicle_input, self)
            modal.interaction_on_submit = self.handle_vehicle_input_submission
            await interaction.response.send_modal(modal)
        else:
            await self.start_vehicle_options_phase(interaction)

    async def handle_vehicle_input_submission(self, interaction: discord.Interaction, results: dict):
        self.data.update(results)
        logger.info(f"Vehicle input submission: {results}")
        await self.start_vehicle_options_phase(interaction)

    def build_vehicle_embed(self, fields: list):
        embed = discord.Embed(
            title="Vehicle Options Phase",
            description="Select vehicle options below.",
            color=Constants.BRAND_COLOR
        )
        embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
        for field in fields:
            value = self.data.get(field["key"], field.get("options", [None])[0])
            embed.add_field(name=field["prompt"], value=str(value), inline=True)
        return embed

    async def start_vehicle_options_phase(self, interaction: discord.Interaction):
        vehicle_option = [f for f in VEHICLE_FIELDS if f["type"] == "option"]
        if len(vehicle_option) > 4:
            group1 = vehicle_option[:4]
            group2 = vehicle_option[4:]
            await self._show_vehicle_options_group(interaction, group1, callback=lambda inter: self._show_vehicle_options_group(inter, group2))
        else:
            await self._show_vehicle_options_group(interaction, vehicle_option)

    async def _show_vehicle_options_group(self, interaction: discord.Interaction, fields: list, callback=None):
        embed = self.build_vehicle_embed(fields)
        view = discord.ui.View(timeout=180)
        for field in fields:
            if len(field["options"]) > 25:
                async def wrapped_callback(interaction: discord.Interaction, key: str, values):
                    self.data[key] = values if isinstance(values, list) else values[0]
                    new_embed = self.build_vehicle_embed(fields)
                    await interaction.response.edit_message(embed=new_embed, view=view)
                    logger.info(f"Paginated vehicle option field {key} set to {self.data[key]}")
                select = PaginatedSelect(field, self.data.get(field["key"], field["options"][0]), wrapped_callback)
                view.add_item(select)
            else:
                opts = [discord.SelectOption(label=o, value=o) for o in field["options"]]
                async def option_callback(interaction: discord.Interaction, key=field["key"]):
                    selected = interaction.data.get("values")
                    if selected:
                        self.data[key] = selected[0]
                    new_embed = self.build_vehicle_embed(fields)
                    await interaction.response.edit_message(embed=new_embed, view=view)
                    logger.info(f"Vehicle option field {key} set to {self.data[key]}")
                select = discord.ui.Select(placeholder=field["prompt"], options=opts, custom_id=f"veh_opt_{field['key']}")
                if field.get("multiple", False):
                    select.max_values = len(field["options"])
                else:
                    select.max_values = 1
                select.callback = option_callback
                view.add_item(select)
        async def on_confirm(interaction: discord.Interaction):
            if callback:
                next_view = NextButtonView(self, callback)
                await safe_send(interaction, content="Proceed to next vehicle options group?", view=next_view)
            else:
                await self.finish_setup(interaction)
        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success, custom_id="confirm_vehicle")
        async def confirm_vehicle(interaction: discord.Interaction):
            await on_confirm(interaction)
        confirm.callback = confirm_vehicle
        view.add_item(confirm)
        await safe_send(interaction, embed=embed, view=view)

    async def finish_setup(self, interaction: discord.Interaction):
        self.data["created_at"] = datetime.utcnow().isoformat()
        self.data["last_checked"] = datetime.utcnow().isoformat()
        self.data["enabled"] = True
        self.data["cache"] = {}
        create_task(self.data)
        
        await self.reload_func()
        
        logger.info(f"Task setup complete: {self.data}")
        embed = discord.Embed(
            title="Task Setup Complete",
            description=f"Task **{self.data['task_id']}** has been set up and scheduled!",
            color=Constants.BRAND_COLOR
        )
        embed.set_footer(text=Constants.BRAND_FOOTER, icon_url=Constants.BRAND_ICON)
        await safe_send(interaction, embed=embed)
