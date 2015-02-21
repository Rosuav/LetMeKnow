from __future__ import print_function
# Note that this is written for Python 2.7 because the Google APIs don't
# seem to work with 3.x (strangely enough, there's nothing telling pip not
# to install it, though). For the most part, I expect that this code should
# be able to run under Py3 unchanged, once the upstream dep is fixed, but
# it hasn't been tested at all.
import argparse
import datetime
import pytz
import sys
import os
import random
import subprocess
from pprint import pprint
from time import sleep

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
		name = arg[0].strip()
		opts = {}
		if name=="calendar" and DEFAULT_CALENDAR:
			opts["default"]=DEFAULT_CALENDAR
			opts["nargs"]="?"
		if "=" in name:
			# Parse out a default value
			name, opts["default"] = name.split("=", 1)
			if name[0]!="-": opts["nargs"]="?"
		p.add_argument(name, help=arg[1].strip(), **opts)
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

def upcoming_events(calendar, offset=0, days=3):
	# Returns only those at least offset seconds from the current time -
	# offset may be negative to return events in the past. The events'
	# times will all be exactly correct; it's only the definition of
	# "upcoming" that is affected by the offset. Returns events within
	# the next 'days' days.
	page_token = None
	now = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=offset)
	tomorrow = now + datetime.timedelta(days=days)
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

@command
def await(calendar, offset, days):
	"""Await the next event on this calendar
	
	calendar: Calendar ID, as shown by list()
	--offset=0: Number of seconds leeway, eg 300 to halt 5 mins before
	--days=7: Number of days in the future to look - gives up if no events in that time
	"""
	offset, days = int(offset), int(days)
	prev = None
	repeat = False # If True, will cycle until we run out of events, rather than doing one and terminating
	while True:
		now = datetime.datetime.now(pytz.utc)
		events = upcoming_events(calendar, offset, days)
		start = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=offset)
		while events:
			if events[0][0] < start: events.pop(0)
			else: break
		if not events:
			print("Nothing to wait for in the entire next week - aborting.")
			return
		target = events[0][0]-datetime.timedelta(seconds=offset)
		delay = target-datetime.datetime.now(pytz.utc)
		if prev and prev!=events[0][1]: print() # Drop to a new line if the target event changes
		print("Sleeping",delay,"until",target,end="                \r")
		sys.stdout.flush()
		prev=events[0][1]
		if delay.total_seconds() > 900:
			# Wait fifteen minutes, then re-check the calendar.
			# This may discover a new event, or may find that the
			# current one has been cancelled, or anything.
			sleep(900)
			continue
		# Wait out the necessary time, counting down the minutes.
		# From here on, we won't go back to the calendar at all.
		# Event changes with less than fifteen minutes to go
		# won't be noticed.
		while delay.total_seconds() > 60:
			sleep(60)
			delay = target-datetime.datetime.now(pytz.utc)
			print("Sleeping",delay,"until",target,end="        \r")
			sys.stdout.flush()
		# Wait the last few seconds.
		sleep(delay.total_seconds())
		# Send an alert, if possible. Otherwise just terminate the process,
		# and allow command chaining to perform whatever alert is needed.
		if ALERT_DIR:
			fn = random.choice(os.listdir(ALERT_DIR))
			print()
			print(fn)
			subprocess.Popen(["vlc",os.path.join(ALERT_DIR,fn)],stdout=open(os.devnull,"w"),stderr=subprocess.STDOUT).wait()
		if not repeat: break # Stop waiting, or go back into the loop and see how we go.
		sleep(1) # Just make absolutely sure that we don't get into an infinite loop, here. We don't want to find ourselves spinning.

if __name__ == "__main__":
	arguments = parser.parse_args().__dict__
	auth()
	globals()[arguments.pop("command")](**arguments)
