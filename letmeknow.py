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
import ssl
import random
import subprocess
from pprint import pprint
from time import sleep

from keys import * # ImportError? Check out keys_sample.py for details.

def auth():
	"""Authenticate with Google. Must be done prior to any other commands."""
	# Some of these imports take quite a while, so don't do them if the user
	# asks for --help or somesuch.
	import httplib2
	import oauth2client.file
	import oauth2client.client
	import oauth2client.tools
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

class DocstringArgs(object):
	"""Configure argparse based on function docstrings

	Basic usage:
	cmdline = DocstringArgs("Program description goes here")
	@cmdline
	def subcommand():
		'''Subcommand description goes here'''
	arguments = cmdline.parse_args()
	globals()[arguments.pop("command")](**arguments)

	Similar in purpose to docopt, but instead of handling all a program's
	arguments in one place, it handles each subcommand as that function's
	docstring.
	"""
	def __init__(self, desc, defaults=None):
		self.parser = argparse.ArgumentParser(description=desc)
		self.subparsers = self.parser.add_subparsers(dest="command", help="Available commands")
		self.defaults = defaults or {}

	def __call__(self, f):
		"""Decorator to make a function available via the command line

		The docstring is parsed to construct argparse configs. The function's
		name becomes a subparser keyword; the first docstring line is the
		description. After that, each line should describe one argument:
		a parameter name, followed by a colon, and then its description.

		If the parameter name is prefixed with "--", it becomes an option,
		otherwise it is a positional arg. If it is followed by "=True",
		it becomes a store_true flag (usually best with options rather than
		positionals); followed by "=" and anything else, it gains a default
		value.

		Any argument named in self.defaults will have their defaults set
		automatically.
		"""
		doc = f.__doc__.split("\n") # Require a docstring
		p = self.subparsers.add_parser(f.__name__, help=doc[0])
		for arg in doc[1:]:
			arg = arg.strip().split(":", 1)
			if len(arg) < 2: continue # Blank lines etc
			name = arg[0].strip()
			opts = {}
			if name in self.defaults:
				opts["default"]=self.defaults[name]
				opts["nargs"]="?"
			if "=" in name:
				# Parse out a default value
				name, opts["default"] = name.split("=", 1)
				if name[0]!="-": opts["nargs"]="?"
				# "arg=True" means store_true rather than an
				# actual default value of "True".
				if opts["default"]=="True":
					del opts["default"]
					opts["action"]="store_true"
			p.add_argument(name, help=arg[1].strip(), **opts)
		return f

	def parse_args(self):
		"""Parse args and return a dictionary (more useful than a namespace)"""
		return self.parser.parse_args().__dict__

defs = {}
if DEFAULT_CALENDAR: defs["calendar"] = DEFAULT_CALENDAR
command = DocstringArgs("Let Me Know - Google Calendar notifications using Frozen", defs)

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
	eventlist=[]
	# Note that I do my own sorting at the end, despite specifying orderBy. This
	# is because, quite frankly, I don't trust Google Calendar's handling of
	# multiple timezones. Normally I expect the final sort to be a simple matter
	# of checking that they're in order, which should be a fast operation.
	while True:
		events = service.events().list(calendarId=calendar, timeMin=now, timeMax=tomorrow, pageToken=page_token, singleEvents=True, orderBy="startTime").execute()
		for event in events['items']:
			eventlist.append((parse(event["start"]["dateTime"]),event['summary'],event["start"].get("timeZone")))
		page_token = events.get('nextPageToken')
		if not page_token: break
	eventlist.sort()
	return eventlist

@command
def show(calendar,tz):
	"""Show upcoming events from one calendar

	calendar: Calendar ID, as shown by list()
	--tz=True: Show timezones
	"""
	now = datetime.datetime.now(pytz.utc)
	for ev in upcoming_events(calendar):
		if tz and ev[2]: ts = str(ev[0]) + " " + ev[2]
		else: ts = ev[0]
		print(ts," - ",ev[0]-now," - ",ev[1])

def set_title(title):
	print("\033]0;"+title, end="\a")
	sys.stdout.flush()

@command
def await(calendar, offset, days, title):
	"""Await the next event on this calendar
	
	calendar: Calendar ID, as shown by list()
	--offset=0: Number of seconds leeway, eg 300 to halt 5 mins before
	--days=7: Number of days in the future to look - gives up if no events in that time
	--title=True: Set the terminal title to show what's happening
	"""
	offset, days = int(offset), int(days)
	prev = None
	while True:
		now = datetime.datetime.now(pytz.utc)
		try:
			events = upcoming_events(calendar, offset, days)
		except (ssl.SSLError, OSError, IOError):
			# SSL or OS/IO errors usually mean connection issues.
			# Hope/assume that there haven't been any event changes,
			# and just retain the previous event list. Yes, this looks
			# like a naive "oh dear, we had an error, just ignore it",
			# but it's a deliberate choice, and one that's going to be
			# safe as long as the 'days' parameter is appropriate.
			pass
		start = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=offset)
		while events:
			if events[0][0] < start: events.pop(0)
			else: break
		if not events:
			print("Nothing to wait for in the entire next",days,"days - aborting.")
			return
		time, event, _ = events[0]
		target = time-datetime.timedelta(seconds=offset)
		delay = target-datetime.datetime.now(pytz.utc)
		if prev and prev!=event: print() # Drop to a new line if the target event changes
		print("Sleeping",delay,"until",target,"-",event,end="\33[K\r")
		sys.stdout.flush()
		prev=event
		if delay.total_seconds() > 900:
			# Wait fifteen minutes, then re-check the calendar.
			# This may discover a new event, or may find that the
			# current one has been cancelled, or anything.
			# Once we're within the last half hour, sleep just five
			# minutes at a time, to make sure we don't have a stupid
			# case where network latency kills us.
			if title: set_title("%dh: %s" % (delay.total_seconds()//3600, event))
			sleep(900 if delay.total_seconds() > 1800 else 300)
			continue
		# Wait out the necessary time, counting down the minutes.
		# From here on, we won't go back to the calendar at all.
		# Event changes with less than fifteen minutes to go
		# won't be noticed.
		if title: set_title(">> "+event)
		while delay.total_seconds() > 60:
			sleep(60 if delay.total_seconds() > 120 else 30)
			delay = target-datetime.datetime.now(pytz.utc)
			print("Sleeping",delay,"until",target,"-",event,end="\33[K\r")
			sys.stdout.flush()
		# Wait the last few seconds.
		sleep(delay.total_seconds())
		# Send an alert, if possible. Otherwise just terminate the process,
		# and allow command chaining to perform whatever alert is needed.
		if ALERT_DIR:
			fn = random.choice(os.listdir(ALERT_DIR))
			print()
			print(fn)
			if title: set_title(fn)
			subprocess.Popen(["vlc",os.path.join(ALERT_DIR,fn)],stdout=open(os.devnull,"w"),stderr=subprocess.STDOUT).wait()
		if not ALERT_REPEAT: break # Stop waiting, or go back into the loop and see how we go.
		sleep(1) # Just make absolutely sure that we don't get into an infinite loop, here. We don't want to find ourselves spinning.

if __name__ == "__main__":
	arguments = command.parse_args()
	auth()
	globals()[arguments.pop("command")](**arguments)
