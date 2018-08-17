"""Let Me Know - Google Calendar notifications using Frozen"""
from __future__ import print_function
# Note that this is written for Python 2.7 because the Google APIs don't
# seem to work with 3.x (strangely enough, there's nothing telling pip not
# to install it, though). For the most part, I expect that this code should
# be able to run under Py3 unchanged, once the upstream dep is fixed, but
# it hasn't been tested at all.
import datetime
import pytz
import sys
import os
import ssl
import random
import socket
import fnmatch
import subprocess
from pprint import pprint
from time import sleep
import clize
from sigtools.modifiers import kwoargs

commands = []
def command(f):
	commands.append(f)
	return f

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
		import argparse
		flags=argparse.Namespace(auth_host_name='localhost', auth_host_port=[8080, 8090], logging_level='ERROR', noauth_local_webserver=False)
		credentials = oauth2client.tools.run_flow(flow, storage, flags)
	# At this point, we should have viable credentials.
	global service
	service = googleapiclient.discovery.build("calendar", "v3", http=credentials.authorize(http=httplib2.Http()))

@command
def list():
	"""List calendars available to your account"""
	# TODO: Do this interactively and allow user to select one, which will be saved away
	auth()
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
			start = event["start"]
			if "dateTime" not in start:
				# All-day events don't have a dateTime field. They have,
				# instead, a date field, and probably won't ever have a
				# timeZone. For now, ignore them; it might be necessary
				# to act as if these are set at midnight.
				assert "date" in start
				continue
			eventlist.append((parse(start["dateTime"]), event.get('summary', '(blank)'), start.get("timeZone")))
		page_token = events.get('nextPageToken')
		if not page_token: break
	eventlist.sort()
	return eventlist

@command
@kwoargs("days","tz")
def show(calendar=DEFAULT_CALENDAR, days=3, tz=False):
	"""Show upcoming events from one calendar

	calendar: Calendar ID, as shown by list()

	days: How far into the future to show events

	tz: Show timezones
	"""
	auth()
	now = datetime.datetime.now(pytz.utc)
	for ev in upcoming_events(calendar,days=days):
		if tz and ev[2]: ts = str(ev[0]) + " " + ev[2]
		else: ts = ev[0]
		print(ts," - ",ev[0]-now," - ",ev[1])

def set_title(title):
	print("\033]0;"+title, end="\a")
	sys.stdout.flush()

def pick_random_file():
	"""Like random.choice(os.listdir(ALERT_DIR)) but respects the weights file"""
	files = dict.fromkeys(os.listdir(ALERT_DIR), 1)
	try:
		with open("weights") as f:
			for line in f:
				if ':' not in line: continue
				weight, pattern = line.strip().split(": ", 1)
				weight = int(weight)
				for fn in fnmatch.filter(files, pattern):
					files[fn] = weight
	except IOError:
		# File doesn't exist? Use default weights.
		pass
	choice = random.randrange(sum(files.values()))
	for fn, weight in files.items():
		choice -= weight
		if choice < 0:
			return fn
	raise ValueError("Unable to randomly pick from %d files" % len(files))

@command
def pickfile(numfiles=1):
	"""Test the random picker

	numfiles: Number of files to select
	"""
	from collections import Counter
	c = Counter(pick_random_file().decode("utf-8") for _ in range(numfiles))
	for fn, count in sorted(c.items(), key=lambda item: -item[1]):
		print(count, fn)

@command
@kwoargs("offset","days","title")
def wait(calendar=DEFAULT_CALENDAR, offset=0, days=7, title=False):
	"""Await the next event on this calendar
	
	calendar: Calendar ID, as shown by list()

	offset: Number of seconds leeway, eg 300 to halt 5 mins before

	days: Number of days in the future to look - gives up if no events in that time

	title: Set the terminal title to show what's happening
	"""
	auth()
	from googleapiclient.http import HttpError
	offset, days = int(offset), int(days)
	prev = None
	while True:
		now = datetime.datetime.now(pytz.utc)
		try:
			events = upcoming_events(calendar, offset, days)
		except (ssl.SSLError, OSError, IOError, socket.error, HttpError):
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
			if title:
				# If we have nearly a whole hour, tag with '+'. If
				# only a little bit, tag with '-'. The boundaries
				# are set such that at least one of them will be
				# shown every hour transition.
				hours, partial = divmod(delay.total_seconds(), 3600)
				if partial < 600: tag = '-'
				elif partial > 3000: tag = '+'
				else: tag = ''
				set_title("%dh%s: %s" % (hours, tag, event))
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
			fn = pick_random_file()
			print()
			print(fn)
			if title: set_title("!! " + event)
			subprocess.Popen(["vlc",os.path.join(ALERT_DIR,fn)],stdout=open(os.devnull,"w"),stderr=subprocess.STDOUT).wait()
		if not ALERT_REPEAT: break # Stop waiting, or go back into the loop and see how we go.
		sleep(1) # Just make absolutely sure that we don't get into an infinite loop, here. We don't want to find ourselves spinning.

if __name__ == "__main__":
	try:
		clize.run(commands)
	except KeyboardInterrupt: pass # Ctrl-C is normal termination
	except Exception as e:
		# On exception, log and reraise as an easy way to print the traceback to two places.
		import traceback
		with open("exception.log", "a") as exc:
			print("*** Uncaught exception at", datetime.datetime.now(), file=exc)
			traceback.print_exc(file=exc)
			print(" - ".join(cls.__name__ for cls in type(e).__mro__))
			print(" - ".join(cls.__name__ for cls in type(e).__mro__), file=exc)
		raise
