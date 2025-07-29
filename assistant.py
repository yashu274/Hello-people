import json
import os
import base64
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from transformers import pipeline
import pytz
import dateparser
from dateparser.search import search_dates

# Email Handler (unchanged)
class EmailHandler:
    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']
        self.service = self.authenticate_gmail()

    def authenticate_gmail(self):
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        try:
            service = build('gmail', 'v1', credentials=creds)
            print("Gmail service authenticated successfully")
            return service
        except Exception as error:
            print(f'Error during Gmail authentication: {error}')
            return None

    def create_message(self, to_email, subject, body, cc_emails=None, bcc_emails=None):
        message = MIMEMultipart()
        message['to'] = to_email
        message['subject'] = subject
        if cc_emails:
            message['cc'] = ', '.join(cc_emails) if isinstance(cc_emails, list) else cc_emails
        if bcc_emails:
            message['bcc'] = ', '.join(bcc_emails) if isinstance(bcc_emails, list) else bcc_emails
        message.attach(MIMEText(body, 'plain'))
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return {'raw': raw_message}

    def send_email(self, to_email, subject, body, cc_emails=None, bcc_emails=None):
        try:
            message = self.create_message(to_email, subject, body, cc_emails, bcc_emails)
            sent_message = self.service.users().messages().send(userId='me', body=message).execute()
            print(f'Email sent successfully! Message ID: {sent_message["id"]}')
            return {'success': True, 'message_id': sent_message['id'], 'details': f'Email sent to {to_email}'}
        except HttpError as error:
            print(f'Error sending email: {error}')
            return {'success': False, 'error': str(error)}

    def get_recent_emails(self, max_results=10):
        try:
            results = self.service.users().messages().list(userId='me', maxResults=max_results).execute()
            messages = results.get('messages', [])
            email_summaries = []
            for message in messages[:5]:
                msg = self.service.users().messages().get(userId='me', id=message['id']).execute()
                headers = msg['payload'].get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
                email_summaries.append({'subject': subject, 'from': sender, 'id': message['id']})
            return email_summaries
        except HttpError as error:
            print(f'Error fetching emails: {error}')
            return []

# Calendar Handler with improved timezone handling
class CalendarHandler:
    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.service = self.authenticate_calendar()
        self.timezone = 'Asia/Kolkata'  # Set to your local timezone

    def authenticate_calendar(self):
        creds = None
        if os.path.exists('calendar_token.pickle'):
            with open('calendar_token.pickle', 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open('calendar_token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        try:
            service = build('calendar', 'v3', credentials=creds)
            print("Calendar service authenticated successfully")
            return service
        except Exception as error:
            print(f'Error during Calendar authentication: {error}')
            return None

    def parse_datetime(self, datetime_str):
        try:
            tz = pytz.timezone(self.timezone)
            now = datetime.now(tz)
            
            # First try to parse the complete string
            parsed = dateparser.parse(
                datetime_str,
                settings={
                    'TIMEZONE': self.timezone,
                    'RETURN_AS_TIMEZONE_AWARE': True,
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': now
                }
            )
            
            if parsed:
                # Ensure the parsed datetime is timezone-aware
                if parsed.tzinfo is None:
                    parsed = tz.localize(parsed)
                return parsed
            
            # If complete parsing fails, try searching for date parts
            parsed_dates = search_dates(
                datetime_str,
                settings={
                    'TIMEZONE': self.timezone,
                    'RETURN_AS_TIMEZONE_AWARE': True,
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': now
                }
            )
            
            if parsed_dates:
                # Find the most specific datetime (prioritize those with time components)
                best_candidate = None
                time_indicators = ['at', 'am', 'pm', ':', 'hr', 'hour']
                
                for substring, date_obj in parsed_dates:
                    if any(indicator in substring.lower() for indicator in time_indicators):
                        best_candidate = date_obj
                        break
                
                if not best_candidate:
                    # If no time found, take the longest date string
                    longest_substring = max(parsed_dates, key=lambda x: len(x[0]))
                    best_candidate = longest_substring[1]
                
                # Ensure timezone is set
                if best_candidate.tzinfo is None:
                    best_candidate = tz.localize(best_candidate)
                return best_candidate

            raise ValueError("Could not parse date string")
        except Exception as e:
            print(f"Error parsing datetime: {e}")
            return None

    def add_event(self, title, start_datetime, end_datetime=None, description="", attendees=None, location=""):
        try:
            if not start_datetime:
                raise ValueError("Start datetime is required")
            
            # Ensure datetimes are timezone-aware
            tz = pytz.timezone(self.timezone)
            if start_datetime.tzinfo is None:
                start_datetime = tz.localize(start_datetime)
                
            if not end_datetime:
                end_datetime = start_datetime + timedelta(hours=1)
            elif end_datetime.tzinfo is None:
                end_datetime = tz.localize(end_datetime)
                
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': start_datetime.isoformat(),
                    'timeZone': self.timezone
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': self.timezone
                },
            }
            if location:
                event['location'] = location
            if attendees:
                event['attendees'] = [{'email': email} for email in attendees]
                
            created = self.service.events().insert(calendarId='primary', body=event).execute()
            print(f"Event created: {created['id']}")
            print(f"Event time: {start_datetime.strftime('%Y-%m-%d %H:%M %Z')}")
            return {'success': True, 'event_id': created['id']}
        except HttpError as error:
            print(f"Error creating event: {error}")
            return {'success': False, 'error': str(error)}
        except Exception as e:
            print(f"Error: {e}")
            return {'success': False, 'error': str(e)}

    def get_upcoming_events(self, max_results=10):
        try:
            now = datetime.now(pytz.timezone(self.timezone)).isoformat()
            events = self.service.events().list(
                calendarId='primary',
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])
            
            return [{
                'summary': e.get('summary', 'No Title'),
                'start': e['start'].get('dateTime', e['start'].get('date')),
                'timeZone': e['start'].get('timeZone', self.timezone)
            } for e in events]
        except HttpError as error:
            print(f"Error fetching events: {error}")
            return []

# Rest of the code remains unchanged...