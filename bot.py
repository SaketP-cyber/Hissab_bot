from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from collections import defaultdict

# ================= CONFIG =================
BOT_TOKEN = "8521800271:AAFmprsmIb6gVOf8tt0yt9dOKCdrXrVu3tc"

ASK_AMOUNT, ASK_PAYER, ASK_SPLIT = range(3)

# ================= STORAGE (In-Memory) =================
GROUP_USERS = defaultdict(dict)
# { group_id: { user_id: user_name } }

EXPENSES = defaultdict(list)
# { group_id: [ {amount, paid_by, split[]} ] }


# ================= HELPERS =================
def register_user(update: Update):
    chat = update.effective_chat
    user = update.effective_user

    if chat and chat.type in ("group", "supergroup"):
        GROUP_USERS[chat.id][user.id] = user.first_name


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)
    await update.message.reply_text(
        "👋 Expense Bot Ready!\n\n"
        "Commands:\n"
        "/add – Add expense\n"
        "/balance – Check balance\n"
        "/cancel – Cancel current action"
    )


# ================= ADD EXPENSE FLOW =================
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)
    context.user_data.clear()
    await update.message.reply_text("💰 Enter amount paid:")
    return ASK_AMOUNT

async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Enter description of the expense:")
    context.user_data["description"] = update.message.text
    return ASK_AMOUNT
async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Please enter a valid number.")
        return ASK_AMOUNT

    amount = int(update.message.text)
    context.user_data["amount"] = amount

    group_id = update.effective_chat.id
    users = GROUP_USERS[group_id]

    if not users:
        await update.message.reply_text("❌ No users registered yet.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"payer:{uid}")]
        for uid, name in users.items()
    ]

    await update.message.reply_text(
        f"💰 Amount: ₹{amount}\nWho paid?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return ASK_PAYER


async def select_payer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payer_id = int(query.data.split(":")[1])
    context.user_data["paid_by"] = payer_id
    context.user_data["split"] = []

    await query.edit_message_text("👥 Select people to split with:")
    return await show_split_buttons(query, context)


async def show_split_buttons(query, context):
    group_id = query.message.chat.id
    users = GROUP_USERS[group_id]
    split = context.user_data["split"]

    keyboard = []
    row = []

    for uid, name in users.items():
        icon = "✅" if uid in split else "⬜"
        row.append(
            InlineKeyboardButton(
                f"{icon} {name}",
                callback_data=f"split:{uid}"
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [InlineKeyboardButton("✔ Confirm", callback_data="confirm")]
    )

    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ASK_SPLIT


async def split_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    split = context.user_data["split"]

    if data.startswith("split:"):
        uid = int(data.split(":")[1])
        if uid in split:
            split.remove(uid)
        else:
            split.append(uid)
        return await show_split_buttons(query, context)

    if data == "confirm":
        if not split:
            await query.answer("Select at least one person!", show_alert=True)
            return ASK_SPLIT

        group_id = query.message.chat.id
        amount = context.user_data["amount"]
        payer = context.user_data["paid_by"]

        EXPENSES[group_id].append({
            "amount": amount,
            "paid_by": payer,
            "split": split.copy(),
            "description": context.user_data.get("description", "")
        })

        names = GROUP_USERS[group_id]
        share = amount / len(split)

        msg = (
            "✅ Expense Added\n\n"
            f"Amount: ₹{amount}\n"
            f"Paid by: {names[payer]}\n"
            f"Split between: {', '.join(names[u] for u in split)}\n"
            f"Per person: ₹{share:.2f}\n"
            f"Description: {context.user_data.get('description', 'No description')}"
        )

        await query.edit_message_text(msg)
        context.user_data.clear()
        return ConversationHandler.END


# ================= BALANCE =================
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)
    group_id = update.effective_chat.id

    if not EXPENSES[group_id]:
        await update.message.reply_text("ℹ️ No expenses yet.")
        return

    balances = defaultdict(float)

    for exp in EXPENSES[group_id]:
        amount = exp["amount"]
        payer = exp["paid_by"]
        split = exp["split"]
        share = amount / len(split)

        balances[payer] += amount
        for uid in split:
            balances[uid] -= share

    names = GROUP_USERS[group_id]
    msg = "📊 Current Balance\n\n"

    for uid, value in balances.items():
        name = names.get(uid, "Unknown")
        if value > 0:
            msg += f"{name} → +₹{value:.2f} (receive)\n"
        elif value < 0:
            msg += f"{name} → -₹{abs(value):.2f} (pay)\n"
        else:
            msg += f"{name} → ₹0.00\n"

    await update.message.reply_text(msg)


# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ASK_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)
            ],
            ASK_PAYER: [
                CallbackQueryHandler(select_payer, pattern="^payer:")
            ],
            ASK_SPLIT: [
                CallbackQueryHandler(split_handler)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(conv_handler)

    print("🤖 Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
