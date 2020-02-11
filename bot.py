import logging
import os

import requests
from dotenv import load_dotenv
from mintersdk import MinterConvertor
from mintersdk.sdk.deeplink import MinterDeeplink
from mintersdk.sdk.transactions import MinterSendCoinTx
from shortuuid import uuid
from telegram import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, InlineQueryHandler, CommandHandler, CallbackQueryHandler

from models import User

load_dotenv()
bot_token = os.environ.get('BOT_TOKEN')

logging.basicConfig(
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	level=logging.INFO)

logger = logging.getLogger(__name__)


def to_pip(bip):
	return MinterConvertor.convert_value(bip, 'pip')


def to_bip(pip):
	return MinterConvertor.convert_value(pip, 'bip')


def get_balance(user):
	existing = requests.post(
		f'https://push.money/api/push/{user.push_id}/balance',
		json={'password': user.password}).json()
	available = existing['bip_value_total']
	return available


def create_deeplink(to, value, coin='BIP', web=True):
	base_url = 'https://bip.to/tx' if web else 'minter:///tx'
	tx = MinterSendCoinTx(coin, to, value, nonce=None, gas_coin=coin)
	deeplink = MinterDeeplink(tx, data_only=True, base_url=base_url)
	return deeplink.generate()


def push_resend(user, amount, virtual=True):
	logger.info(f'resend {user}, {amount}')
	response = requests.post(
		f'https://push.money/api/spend/{user.push_id}', json={
			'password': user.password,
			'option': 'resend',
			'params': {'amount': amount, 'virtual': virtual}
		})
	return response.json()['new_link_id']


def push_topup(user_id, amount, password=None):
	user = User.get_or_none(tg_id=user_id)
	if user:
		existing = requests.post(
			f'https://push.money/api/push/{user.push_id}/balance',
			json={'password': user.password}).json()
		return {
			'deeplink': create_deeplink(existing['address'], amount, web=True),
			'amount': amount
		}

	push = requests.post(
		'https://push.money/api/push/create',
		json={'amount': amount, 'password': password}).json()
	User.create(tg_id=user_id, push_id=push['link_id'], password=password)
	return {'deeplink': push['deeplink'].replace('minter:///', 'https://bip.to/'), 'amount': amount}


def start(update, context):
	chat = update.message.chat
	user_id = update.message.from_user.id
	if context.args:
		amount = float(to_bip(context.args[0]))
		user = User.get_or_none(tg_id=user_id)
		if user:
			topup_info = push_topup(user_id, amount)
			chat.send_message(
				f'Need {topup_info["amount"]} more BIP for top up',
				reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
					f'Press to top-up ({topup_info["amount"]} BIP)', url=topup_info['deeplink']
				)], [InlineKeyboardButton(
					'Show wallet address', callback_data='address'
				)], [InlineKeyboardButton('Start sending', switch_inline_query='')]
			]))
			return

		password = uuid()
		topup_info = push_topup(user_id, amount, password=password)
		chat.send_message("Hey. I will help you send money in chats.")
		chat.send_message(
			f'Give me some coins.',
			reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
				f'Press to top up ({topup_info["amount"]} BIP)', url=topup_info['deeplink']
			)], [InlineKeyboardButton(
				'Show wallet address', callback_data='address'
			)], [InlineKeyboardButton('Start sending', switch_inline_query='')]
		]))
		return

	user = User.get_or_none(tg_id=user_id)
	greet = "Hey. I will help you send money in chats."
	if user:
		greet = "Hey! You already have an account"

	password = uuid()
	topup_info = push_topup(user_id, 10, password=password)
	chat.send_message(greet)
	chat.send_message(
		f'Give me some coins.',
		reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
			f'Press to top up ({topup_info["amount"]} BIP)', url=topup_info['deeplink']
		)], [InlineKeyboardButton(
			'Show wallet address', callback_data='address'
		)], [InlineKeyboardButton('Start sending', switch_inline_query='')]
		]))


def help(update, context):
	update.message.chat.send_message('TODO::write help text')


def error(update, context):
	logger.warning('Error: "%s"\nUpdate: "%s"', context.error, update)


def address(update, context):
	user_id = update.callback_query.from_user.id
	user = User.get_or_none(tg_id=user_id)
	existing = requests.post(
		f'https://push.money/api/push/{user.push_id}/balance',
		json={'password': user.password}).json()
	context.bot.send_message(user_id, existing['address'])


def inline_handler(update, context):
	query = update.inline_query.query
	try:
		amount = int(query)
	except ValueError:
		return
	if not query:
		return
	user_id = update.inline_query.from_user.id
	user = User.get_or_none(tg_id=user_id)
	logging.info(f'Received query {query} from {update.inline_query.from_user.username}')
	if not user:
		update.inline_query.answer(
			[],
			switch_pm_text=f'Create your wallet first',
			switch_pm_parameter=f'{to_pip(amount + 0.01)}',
			cache_time=0)
		return
	balance = get_balance(user)
	logging.info(f'{update.inline_query.from_user.username} balance {balance}')
	if balance < amount:
		need_bip = amount - balance + 0.01
		need = to_pip(need_bip)
		update.inline_query.answer(
			[],
			switch_pm_text=f'Not enough money (need {round(need_bip, 4)}). Top up first',
			switch_pm_parameter=f'{need}',
			cache_time=0)
		return

	token = push_resend(user, amount, virtual=True)
	results = [
		InlineQueryResultArticle(
			token, f'Push {amount} BIP to current chat',
			InputTextMessageContent('Click the button to receive and spend Blockchain Instant Payment'),
			reply_markup=InlineKeyboardMarkup([
				[InlineKeyboardButton(f'Get {amount} BIP', url=f'https://yyy.cash/push/{token}')]
			]),
			description='Send yyy.cash one-time wallet to this chat')
	]
	update.inline_query.answer(results, cache_time=0)


def main():
	bot = Updater(bot_token, use_context=True)
	dp = bot.dispatcher
	dp.add_handler(CommandHandler("start", start))
	dp.add_handler(CommandHandler("help", help))
	dp.add_handler(InlineQueryHandler(inline_handler))
	dp.add_handler(CallbackQueryHandler(address, pattern='^address$'))
	dp.add_error_handler(error)

	bot.start_polling()


if __name__ == '__main__':
	main()
