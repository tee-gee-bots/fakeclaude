# src/bot.py
import asyncio
import os
import pathlib
import random
import requests
import logging
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes

from api_client import MessageAPIClient

# Configure logging
MY_BOT_NAME='fakeclaude'
log_level = os.getenv('LOG_LEVEL', 'INFO')
numeric_level = getattr(logging, log_level.upper(), logging.INFO)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=numeric_level
)
logger = logging.getLogger(MY_BOT_NAME)

# API configuration from environment
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://localhost')
api = MessageAPIClient(MY_BOT_NAME, API_ENDPOINT)

DATA_DIR = os.path.join(pathlib.Path(__file__).parent.resolve(), 'data')
logger.info(__file__)
logger.info(pathlib.Path(__file__).parent.resolve())
logger.info(f'Setting {DATA_DIR=}')

async def health_check():
    """Check bot's health and API connection."""
    try:
        api_url = f'{API_ENDPOINT}/health'
        logger.info(f'Checking API health at: {api_url}')
        
        response = requests.get(api_url, timeout=5)
        logger.info(f'API Response: {response.status_code} - {response.text}')
        api_status = response.status_code == 200
        
        result = {
            'status': 'healthy',
            'api_connected': api_status,
            'api_endpoint': API_ENDPOINT,
            'api_status_code': response.status_code,
            'api_response': response.text
        }
        logger.info(f'Health check result: {result}')
        return result
    except Exception as e:
        logging.error(f'Health check failed: {str(e)}')
        return {
            'status': 'unhealthy',
            'error': str(e),
            'api_endpoint': API_ENDPOINT
        }

# Docker healthcheck
from aiohttp import web
async def handle_health(request):
    health = await health_check()
    status = 200 if health['status'] == 'healthy' else 500
    return web.json_response(health, status=status)


def get_random_file(directory):
    try:
        files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
        if not files:
            logger.error(f'Could not find any files in {directory=}')
            return ''
    except Exception as e:
        error = f'Failed to populate list of files in {directory} - {e.args[0]}'
        logger.error(error)
        return ''
    
    try:
        random_file = random.choice(files)
        random_file_fullpath = os.path.normpath(os.path.join(directory, random_file))
        if not os.path.isfile(random_file_fullpath):
            logger.error(f'Failed to choose random file from directory - {random_file_fullpath} does not exist')
            return ''
        return random_file_fullpath
    except Exception as e:
        error = f'Failed to get path to random file \'{random_file}\' in \'{directory}\' - {e.args[0]}'
        logger.error(error)
        return ''


def read_file_content(file):
    if not file:
        logger.error(f'File path argument cannot be empty: {file=}')
        return '', file
    if os.path.getsize(file) == 0:
        logger.error(f'File is empty \'{file}\'')
        return '', file

    try:
        with open(file, 'r') as f:
            content = f.read()
        return content, file
    except FileNotFoundError as e:
        logger.error(f'File not found - {e.args[0]}')
        return '', file
    except IOError as e:
        logger.error(f'Failed to read \'{file}\' - {e.args[0]}')
        return '', file


def get_default_response(source_dir):
    source_file = os.path.join(source_dir, 'default.txt')
    return read_file_content(source_file), source_file


def gen_claude_prompt(source_dir):
    try:
        response, source_file = read_file_content(get_random_file(source_dir))
        if not response:
            response, source_file = get_default_response(source_dir)
        return response, source_file
    except Exception as e:
        error = f'Failed to get valid response from {source_dir=} - {e.args[0]}'
        logger.error(error)
        raise Exception(error)

# Define command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(f'Hello! I am your test bot. My name is {MY_BOT_NAME}')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /ping is issued."""
    health = await health_check()
    await update.message.reply_text('pong! connection to server is {}'.format(health['status']))

async def reply_with_random_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    source_dir = os.path.join(DATA_DIR, 'claude_prompts')
    if not os.path.isdir(source_dir):
        logger.error(f'Missing directory {source_dir}')
    
    response, source_file = gen_claude_prompt(source_dir)
    if not response:
        logger.error(f'Failed to generate response from {source_file=}')
        await update.message.reply_text('You have run out of free messages until 8am tomorrow')

    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text=response,
                                   reply_markup=ForceReply())

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
Available commands:
/start - Start the bot
/help - Show this help message

/ping - Check if bot is connected to server
/fetch - Show last messages in server
/ask_claude - Returns a claude response
    """
    await update.message.reply_text(help_text)


def main():
    """Start the bot"""
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logging.error('No TELEGRAM_TOKEN provided')
        return

    # Create application
    application = Application.builder().token(token).build()

    # Add command handlers (starts with /your-command)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('ask_claude', reply_with_random_file))

    # Start health check server
    app = web.Application()
    app.router.add_get('/health', handle_health)
    runner = web.AppRunner(app)

    async def start_health_server():
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()

    # Run both the bot and health server
    asyncio.get_event_loop().run_until_complete(start_health_server())
    application.run_polling()

if __name__ == '__main__':
    main()
