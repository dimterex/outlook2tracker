import asyncio
import sys
import os
import time
import warnings
import socket

from datetime import datetime, timezone, timedelta

from modules.connections.outlook_connection import Outlook_Connection
from modules.models.configuration import Configuration
from modules.models.log_service import Logger_Service
from modules.models.outlook_meeting import Outlook_Meeting
from modules.rabbitmq.messages.api_controller import Api_Controller
from modules.rabbitmq.messages.discord.send_message import Send_Message
from modules.rabbitmq.messages.identificators import WORKLOG_QUEUE, DISCORD_QUEUE, OUTLOOK_QUEUE, \
    GET_NEXT_MEETING_MESSAGE, LOGGER_QUEUE
from modules.rabbitmq.messages.outlook.get_next_meeting import PROMISE_ID_PROPERTY
from modules.rabbitmq.publisher import Publisher
from modules.rabbitmq.receive import Consumer

SETTINGS_FILE = 'settings.json'
HOST_ENVIRON = 'RABBIT_HOST'
PORT_ENVIRON = 'RABBIT_PORT'


def convert_rawdate_to_datetime(raw_date: str):
    # convert from string format to datetime format
    return datetime.strptime(raw_date, '%Y/%m/%d')


def main():
    # host = socket.gethostbyname(os.environ[HOST_ENVIRON])
    host = os.environ[HOST_ENVIRON]
    raw_port = os.environ[PORT_ENVIRON]
    port = int(raw_port)

    logger_service = Logger_Service('Outlook_Application')
    api_controller = Api_Controller(logger_service)
    ampq_url = f'amqp://guest:guest@{host}:{port}'
    publisher = Publisher(ampq_url)
    consumer = Consumer(ampq_url, OUTLOOK_QUEUE, api_controller, logger_service)

    def send_log(log_message):
        publisher.send_message(LOGGER_QUEUE, log_message.to_json())

    logger_service.configure_action(send_log)

    with open(SETTINGS_FILE, 'r', encoding='utf8') as json_file:
        raw_data = json_file.read()
        configuration = Configuration(raw_data)

    domain_login = f'{configuration.domain}\\{configuration.login}'
    outlook_connection = Outlook_Connection(configuration.outlook, configuration.email, domain_login, configuration.password, logger_service)

    def get_next_meeting(obj):
        promise_id = obj[PROMISE_ID_PROPERTY]
        start_time = datetime.utcnow()
        start_time = start_time.replace(tzinfo=timezone.utc)
        meetings = outlook_connection.get_meeting(start_time)
        selected_meetings: list[Outlook_Meeting] = []
        for meeting in meetings:
            if start_time > meeting.start:
                continue
            if len(selected_meetings) == 0:
                selected_meetings.append(meeting)
            else:
                first_item = selected_meetings[0]
                if first_item.start == meeting.start:
                    selected_meetings.append(meeting)

        if len(selected_meetings) == 0:
            publisher.send_message(DISCORD_QUEUE, Send_Message(promise_id, 'Not meetings today...').to_json())
            return

        for meeting in selected_meetings:
            meeting_start_time = meeting.start.replace(hour=meeting.start.hour + 7)
            meeting_end_time = meeting.end.replace(hour=meeting.end.hour + 7)
            message: list[str] = [
                f'Name: {meeting.name}'
                f'\n\tDate: {meeting_start_time.day}-{meeting_start_time.month}-{meeting_start_time.year}'
                f'\n\tTime: {meeting_start_time.hour}:{meeting_start_time.minute}-{meeting_end_time.hour}:{meeting_end_time.minute}'
                f'\n\tLocation: {meeting.location}'
                f'\n\tContent: {meeting.description}'
            ]
            publisher.send_message(DISCORD_QUEUE, Send_Message(promise_id, '\n'.join(message)).to_json())

    api_controller.configure(OUTLOOK_QUEUE, GET_NEXT_MEETING_MESSAGE, get_next_meeting)

    consumer.start()


if __name__ == '__main__':
    warnings.filterwarnings("ignore")
    print('Starting')
    main()
    print('Started')

    try:
        while True:
            time.sleep(1)
    finally:
        pass
