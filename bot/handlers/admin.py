from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config.settings import config
from database import models
from utils import panel
from utils.logger import logger


router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


@router.message(Command("reply"))
async def reply_ticket(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return

    args = (command.args or "").strip()
    ticket_part, _, answer = args.partition(" ")

    if not ticket_part.isdigit() or not answer.strip():
        await message.answer("Формат: <code>/reply НОМЕР текст ответа</code>")
        return

    ticket = await models.get_ticket(int(ticket_part))

    if not ticket:
        await message.answer(f"Обращение №{ticket_part} не найдено.")
        return

    answer = answer.strip()

    try:
        await message.bot.send_message(
            ticket.user_id,
            f"💬 <b>Ответ поддержки по обращению №{ticket.id}</b>\n\n{escape(answer)}",
        )
    except TelegramAPIError as error:
        logger.warning("Не удалось отправить ответ пользователю: %s", error)
        await message.answer("Пользователь недоступен — сообщение не доставлено.")
        return

    await models.answer_ticket(ticket.id, answer)
    await message.answer(f"Ответ по обращению №{ticket.id} отправлен.")


@router.message(Command("stars"))
async def stars_report(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    stuck = await models.stuck_star_payments()

    if not stuck:
        await message.answer("Незавершённых платежей звёздами нет.")
        return

    lines = ["<b>Платежи звёздами без подписки</b>", ""]
    budget = 3800
    shown = 0

    for row in stuck:
        unit = "★" if row["currency"] == "XTR" else row["currency"]
        block = (
            f"<code>{escape(row['charge_id'])}</code>\n"
            f"  {row['status']} · {row['amount']}{unit} · тариф {escape(row['plan_code'])}\n"
            f"  учётка: {escape(row['panel_login'] or '—')} · {row['created_at']}\n"
            f"  причина: {escape((row['note'] or '—')[:120])}"
        )

        if budget - len(block) < 0:
            break

        budget -= len(block)
        shown += 1
        lines.append(block)

    if shown < len(stuck):
        lines.append(f"\n…и ещё {len(stuck) - shown}. Разберите показанные и повторите.")

    await message.answer("\n".join(lines))


@router.message(Command("refund"))
async def refund_stars(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return

    args = (command.args or "").strip()
    charge_id, _, reason = args.partition(" ")
    reason = reason.strip() or "возврат звёзд администратором"

    if not charge_id:
        await message.answer(
            "Формат: <code>/refund ИДЕНТИФИКАТОР_ПЛАТЕЖА причина</code>\n"
            "Список платежей — <code>/stars</code>"
        )
        return

    row = await models.star_payment(charge_id)

    if not row:
        await message.answer("Такого платежа нет. Проверьте идентификатор: <code>/stars</code>")
        return

    if row["status"] == "refunded":
        await message.answer("По этому платежу возврат уже сделан.")
        return

    if row["currency"] != "XTR":
        await message.answer(
            "Это оплата не звёздами — вернуть её этой командой нельзя. "
            "Возврат по карте делается на стороне платёжного сервиса."
        )
        return

    money_back = row["status"] == "refunded_outside"

    await models.finish_star_payment(charge_id, "refunding", reason)

    if not money_back:
        try:
            await message.bot.refund_star_payment(
                user_id=row["user_id"], telegram_payment_charge_id=charge_id
            )
        except TelegramAPIError as error:
            text = str(error).lower()
            if "already" in text or "refunded" in text:
                logger.info("звёзды по %s уже возвращены — снимаем подписку", charge_id)
            else:
                logger.error("Telegram не вернул звёзды по %s: %s", charge_id, error)
                await models.finish_star_payment(charge_id, row["status"], row["note"])
                await message.answer(f"Telegram отказал в возврате: {escape(str(error))}")
                return

    order_id = None

    try:
        order_id = await panel.refund_by_payment("telegram", charge_id, reason)
    except panel.PanelError as error:
        if getattr(error, "status", None) != 404:
            logger.error("звёзды по %s вернули, а подписку снять не вышло: %s", charge_id, error)
            await models.finish_star_payment(charge_id, "refund_partial", str(error)[:400])
            await message.answer(
                "Звёзды вернулись, но снять подписку не удалось — сделайте это в панели вручную.\n"
                f"Причина: {escape(str(error))}"
            )
            return

        logger.info("по платежу %s заказа нет — снимать нечего", charge_id)

    await models.finish_star_payment(charge_id, "refunded", reason)

    try:
        await message.bot.send_message(
            row["user_id"],
            f"↩️ <b>Звёзды возвращены</b>\n\n{escape(reason)}\n\n"
            "Подписка, оплаченная этим платежом, снята.",
        )
    except TelegramAPIError:
        logger.info("о возврате %s человеку сообщить не удалось", charge_id)

    await message.answer(
        f"Возврат сделан.\nПлатёж: <code>{escape(charge_id)}</code>\n"
        + (
            f"Заказ: <code>{order_id[:8]}</code> — подписка снята."
            if order_id
            else "Заказа по этому платежу не было — снимать было нечего."
        )
    )
