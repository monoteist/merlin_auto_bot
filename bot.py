import telebot
from merlin import get_cars, get_url

API_TOKEN = '968973363:AAFUWqxeWI_7iPz0mu4zUltiHahATemu_wU'
bot = telebot.TeleBot(API_TOKEN)


@bot.message_handler(commands=['run'])
def start(message):
    print("working")
    auction_chat_id = 156649256
    # url = 'https://www.merlin.ie/stock/?culture=en-GB&locationid=36&saleid=482&excludeClosed=true&page=3&pagesize=74&sortby=reference_asc'
    url = get_url()
    get_cars(url, auction_chat_id, bot)


if __name__ == '__main__':
    bot.polling()
 