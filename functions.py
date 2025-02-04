from google.auth.transport.requests import Request
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dateutil import parser
from typing import Annotated
from livekit.agents import llm
import logging
import sqlite3
import datetime
import base64
import os

# Defining Scope for accessing Google servics
SCOPES_calendar = ["https://www.googleapis.com/auth/calendar"]
SCOPES_gmail= ['https://www.googleapis.com/auth/gmail.compose']

# Setting up a logging system to track actions in the programm
logger = logging.getLogger("office-assistant")
logger.setLevel(logging.INFO)



class AssistantFnc(llm.FunctionContext):
    def __init__(self) -> None:
        super().__init__()
        self._db_path = os.path.abspath("customer_data.db")
        self._setup_database()



    def _setup_database(self):
        """Initialize the database and create tables if not exists."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL
                )
            """)
            conn.commit()



    def _setup_calendar_service(self):
        """Authenticate and return the Google Calendar service."""
        creds = None
        if os.path.exists("token_calendar.json"):
            creds = Credentials.from_authorized_user_file("token_calendar.json", SCOPES_calendar)
        
        # If no valid credentials are found, the user has to authenticate via browser 
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials_calendar.json", SCOPES_calendar
                )
                creds = flow.run_local_server(port=0)
            with open("token_calendar.json", "w") as token:     # credentials for further use
                token.write(creds.to_json())

        return build("calendar", "v3", credentials=creds)
    


    def _setup_gmail_service(self):
        """Authenticate the user and save the credentials."""
        creds = None
        script_dir = os.path.dirname(os.path.abspath(__file__))  # Current script's directory
        token_path = os.path.join(script_dir, "token_gmail.json")
        credentials_path = os.path.join(script_dir, "credentials_gmail.json")
        
        # Load the saved credentials if token.json exists
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path)
        
        # If no valid credentials are found, the user has to authenticate via browser 
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES_gmail)
                creds = flow.run_local_server(port=0)

            # Save the credentials to token.json
            with open(token_path, 'w') as token_file:       # credentials for further use
                token_file.write(creds.to_json())
        
        return build('gmail', 'v1', credentials=creds)
    



    # function to create events in Google Calendar

    @llm.ai_callable(description="Create a new event in Google Calendar.")
    def create_event(self, summary: str, description: str, start: str, end: str, timezone: str = "Europe/Vienna"):
        """Creates a new event in the user's Google Calendar."""
        try:
            service = self._setup_calendar_service()

            # Parsing the start and end times into different format
            start = parser.parse(start).isoformat()
            end = parser.parse(end).isoformat()

            # event dictionary with necessary details
            event = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start, "timeZone": timezone},
                "end": {"dateTime": end, "timeZone": timezone},
            }

            # Inserting event into user's calendar
            event_result = service.events().insert(calendarId="primary", body=event).execute()
            return f"Event created: {event_result.get('htmlLink')}"
        
        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return "Failed to create event."
        



    # function to retrieve user's upcoming events from Google Calendar

    @llm.ai_callable(description="Retrieve upcoming Google Calendar events.")
    def get_upcoming_events(self, max_results: int = 10):
        """Fetches upcoming events from the user's Google Calendar."""
        try:
            service = self._setup_calendar_service()                 # setting up Calendar API service
            
            now = datetime.datetime.utcnow().isoformat() + "Z"       # current time as starting point
            
            events_result = service.events().list(                   # fetching upcoming events
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])                  # extracting events

            if not events:
                return "No upcoming events found."
            
            # processing event
            return f"{[{'start': event['start'].get('dateTime', event['start'].get('date')), 'summary': event['summary']} for event in events]}"

        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return "Failed to fetch events."
        except KeyError as e:
            logger.error(f"Missing key in event data: {e}")
            return "Invalid event data format."
        



    # function to create email drafts in Gmail

    @llm.ai_callable(description="Create a new draft in Google Mail.")
    def gmail_create_draft(self,
        recipient: Annotated[str, llm.TypeInfo(description="Email recipient")],
        subject: Annotated[str, llm.TypeInfo(description="Email subject")],
        body: Annotated[str, llm.TypeInfo(description="Email body")],
    ):
        """Create and insert a draft email."""
        service = self._setup_gmail_service()

        try:
            # Create email message
            message = EmailMessage()
            message.set_content(body)
            message["To"] = recipient
            message["Subject"] = subject

            # Encode the message 
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {"message": {"raw": encoded_message}}

            # Create a draft with Gmail API
            draft = service.users().drafts().create(userId="me", body=create_message).execute()
            logger.info(f'Draft id: {draft["id"]}\nDraft message: {draft["message"]}')
            return draft
        
        except HttpError as error:
            logger.info(f"An error occurred: {error}")
            draft = None
            return "Failed to create draft"




    # function to send mails in Gmail

    @llm.ai_callable(description="Send a new mail in Google Mail.")
    def gmail_send_message(self,
        recipient: Annotated[str, llm.TypeInfo(description="Email recipient")],
        subject: Annotated[str, llm.TypeInfo(description="Email subject")],
        body: Annotated[str, llm.TypeInfo(description="Email body")],
    ):
        """Create and send an email message
        Print the returned  message id
        Returns: Message object, including message id
        """
        service = self._setup_gmail_service()

        try:
            # creating email message
            message = EmailMessage()
            message.set_content(body)
            message["To"] = recipient
            message["Subject"] = subject

            # Encode the message
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {"raw": encoded_message}

            # send mail using Gmail API
            send_message = (
                service.users()
                .messages()
                .send(userId="me", body=create_message)
                .execute()
            )
            logger.info(f'Message Id: {send_message["id"]}')
            return send_message
        
        except HttpError as error:
            logger.info(f"An error occurred: {error}")
            send_message = None
            return "Failed to send mail"



    
    # function to add customers into SQL database

    @llm.ai_callable(description="Add a customer to the database")
    def add_customer(self, name: str, email: str):
        try:
            # connect with the database and insert new entry
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO customers (name, email) VALUES (?, ?)", (name, email))
                conn.commit()

            return f"Customer {name} added successfully."
        
        except sqlite3.IntegrityError:
            return f"Customer {name} already exists."
        


   # functino to query SQL database     

    @llm.ai_callable(description="Get customer information")
    def get_customer(self, name: str):

        # connect with the database and query it
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers WHERE name = ?", (name,))
            result = cursor.fetchone()

        if result:
            return f"Customer Name: {result[1]}, Email: {result[2]}"
        
        return f"Customer {name} not found."
    
