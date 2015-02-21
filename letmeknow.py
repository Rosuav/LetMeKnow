from __future__ import print_function
# Note that this is written for Python 2.7 because the Google APIs don't
# seem to work with 3.x (strangely enough, there's nothing telling pip not
# to install it, though). For the most part, I expect that this code should
# be able to run under Py3 unchanged, once the upstream dep is fixed, but
# it hasn't been tested at all.
import argparse
import datetime
import pytz
from pprint import pprint

from keys import * # ImportError? Check out keys_sample.py for details.

parser = argparse.ArgumentParser(description="Let Me Know - Google Calendar notifications using Frozen")
subparsers = parser.add_subparsers(dest="command", help="Available commands")

def auth():
	"""Authenticate with Google. Must be done prior to any other commands."""
	# Some of these imports take quite a while, so don't do them if the user
	# asks for --help or somesuch.
	import httplib2
	import oauth2client.file
	import oauth2client.client
	import googleapiclient.discovery
	storage = oauth2client.file.Storage("credentials.dat")
	credentials = storage.get()
	if not credentials or credentials.invalid:
		# HACK: Use the run_flow function to save some trouble, but don't
		# actually pass it any of the args from the command line. TODO: Use
		# our own code here instead.
		flow = oauth2client.client.OAuth2WebServerFlow(client_id=CLIENT_ID,client_secret=CLIENT_SECRET,
			scope='https://www.googleapis.com/auth/calendar.readonly', # Don't need any read/write access
			user_agent='Let Me Know')
		flags=argparse.Namespace(auth_host_name='localhost', auth_host_port=[8080, 8090], logging_level='ERROR', noauth_local_webserver=False)
		credentials = oauth2client.tools.run_flow(flow, storage, flags)
	# At this point, we should have viable credentials.
	global service
	service = googleapiclient.discovery.build("calendar", "v3", http=credentials.authorize(http=httplib2.Http()))

def command(f):
	doc = f.__doc__.split("\n") # Require a docstring
	p = subparsers.add_parser(f.__name__, help=doc[0])
	for arg in doc[1:]:
		arg = arg.strip().split(":", 1)
		if len(arg) < 2: continue # Blank lines etc
		p.add_argument(arg[0].strip(), help=arg[1].strip())
	return f

@command
def list():
	"""List calendars available to your account"""
	# TODO: Do this interactively and allow user to select one, which will be saved away
	page_token = None
	while True:
		calendar_list = service.calendarList().list(pageToken=page_token).execute()
		for cal in calendar_list['items']:
			print(cal['id'])
			print(u'\t'+cal['summary'])
		page_token = calendar_list.get('nextPageToken')
		if not page_token: break

class tz(datetime.tzinfo):
	def __init__(self, desc):
		self.desc = desc
		# Calculate the offset, which is what we really want
		# The descriptor should be "-HH:MM" where HH is hours
		# and MM is minutes, and the first character is a minus
		# sign for negative or is assumed to be a plus sign.
		hr = int(desc[1:3])
		min = int(desc[4:])
		if desc[0]=='-': hr, min = -hr, -min # Negate both parts
		ofs = datetime.timedelta(hours=hr, minutes=min)
		self.ofs = ofs
	def utcoffset(self, datetime):
		return self.ofs
	def __repr__(self):
		return "<TZ: "+self.desc+">"

def parse(date):
	"""Parse a datetime string that Google produces and return an aware datetime object"""
	# Start with the main work.
	d = datetime.datetime.strptime(date[:-6],"%Y-%m-%dT%H:%M:%S")
	# Now let's try... TRY to patch in a timezone.
	return d.replace(tzinfo=tz(date[-6:]))

def upcoming_events(calendar):
	page_token = None
	now = datetime.datetime.now(pytz.utc)
	tomorrow = now + datetime.timedelta(days=3)
	now,tomorrow = (x.strftime("%Y-%m-%dT%H:%M:%SZ") for x in (now,tomorrow))
	# Recurring events are a bit of a pain. With those, the initial event
	# object actually has the *first* start time used, not the next instance.
	# So we have to go and do another call for those, fetching the instances
	# that are within the current time frame. Additionally, the events appear
	# to be sorted by that first start time, so when there are recurrings, we
	# have to slot them into the correct positions. To do this, we need some
	# kind of reliable sorting mechanism. I could probably cheat and just sort
	# by the dateTime strings, as they'll normally all be in the same timezone
	# (at least, they aren't being given in the event's timezone), but for
	# safety's sake, we parse them out - see tz() and parse() above.
	eventlist=[]
	while True:
		events = service.events().list(calendarId=calendar, timeMin=now, timeMax=tomorrow, pageToken=page_token).execute()
		for event in events['items']:
			if "recurrence" in event:
				for inst in service.events().instances(calendarId=calendar, eventId=event['id'], timeMin=now, timeMax=tomorrow).execute()['items']:
					eventlist.append((parse(inst["start"]["dateTime"]),event['summary']))
			else:
				eventlist.append((parse(event["start"]["dateTime"]),event['summary']))
		page_token = events.get('nextPageToken')
		if not page_token: break
	eventlist.sort()
	return eventlist

@command
def show(calendar):
	"""Show upcoming events from one calendar

	calendar: Calendar ID, as shown by list()
	"""
	now = datetime.datetime.now(pytz.utc)
	for ev in upcoming_events(calendar):
		print(ev[0]," - ",ev[0]-now," - ",ev[1])

if __name__ == "__main__":
	arguments = parser.parse_args().__dict__
	auth()
	globals()[arguments.pop("command")](**arguments)
