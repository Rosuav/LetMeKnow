"""Let Me Know - Google Calendar notifications using Frozen"""
from __future__ import print_function
# Note that this is aimed at being compatible with Python 2.7 and 3.5+.
# However, I have not tested in all versions thoroughly.
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
from time import time, sleep
import clize
from sigtools.modifiers import kwoargs, annotate
# uritemplate doesn't work on 3.9, and drops a warning on 3.8.
import collections.abc; collections.MutableMapping = collections.abc.MutableMapping

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
			scope='https://www.googleapis.com/auth/calendar' + '.readonly' * READ_ONLY, # Don't normally need any read/write access
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

def upcoming_events(calendar, offset=0, days=3, include_all_day=False):
	"""Fetch a list of events in the next few days.

	'calendar' is either a GCal calendar ID, or multiple of them joined
	with commas. (The separator may change in the future if a conflict
	is discovered. Single calendar ID is dependable.)

	Returns only those at least offset seconds from the current time -
	offset may be negative to return events in the past. The events'
	times will all be exactly correct; it's only the definition of
	"upcoming" that is affected by the offset.

	All-day events are generally suppressed as uninteresting. If included,
	they are timestamped at midnight UTC.

	Returns events within the next 'days' days as a list of three-tuples:
	(timestamp, description, raw_info)
	"""
	page_token = None
	now = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=offset)
	tomorrow = now + datetime.timedelta(days=days)
	now,tomorrow = (x.strftime("%Y-%m-%dT%H:%M:%SZ") for x in (now,tomorrow))
	eventlist=[]
	for calendar in calendar.split(","):
		# Note that I do my own sorting at the end, despite specifying orderBy. In
		# the common case where a single calendar is being used, this ought to be
		# redundant, but quite frankly, I don't trust Google Calendar's handling of
		# multiple timezones, and it's safer and simpler to just do the sort. The
		# algorithm used by CPython (TimSort) handles merges and sort checks very
		# efficiently, so it's not a high cost (esp compared to the network queries).
		while True:
			events = service.events().list(calendarId=calendar, timeMin=now, timeMax=tomorrow, pageToken=page_token, singleEvents=True, orderBy="startTime").execute()
			for event in events['items']:
				start = event["start"]
				if "dateTime" not in start:
					# All-day events don't have a dateTime field. They have,
					# instead, a date field, and probably won't ever have a
					# timeZone.
					if not include_all_day: continue
					ts = datetime.datetime(*map(int, start["date"].split("-")), tzinfo=pytz.utc)
				else:
					ts = parse(start["dateTime"])
				eventlist.append((ts, event.get('summary', '(blank)'), event))
			page_token = events.get('nextPageToken')
			if not page_token: break
	eventlist.sort(key=lambda ev: ev[:2])
	return eventlist

@command
@kwoargs("days","tz")
def show(calendar=DEFAULT_CALENDAR, days=3, tz=False):
	"""Show upcoming events from one or more calendars

	calendar: Calendar ID, as shown by list()

	days: How far into the future to show events

	tz: Show timezones
	"""
	auth()
	now = datetime.datetime.now(pytz.utc)
	for ts, desc, raw in upcoming_events(calendar, days=days, include_all_day=True):
		delay = ts - now
		if tz and "timeZone" in raw["start"]:
			ts = "%s %s" % (ts, raw["start"]["timeZone"])
		print(ts, " - ", delay, " - ", desc)

def migrate(purgeme, from_cal, to_cal, convert=lambda info: True, days=7, purge=False):
	"""Import/migrate events from one cal to another.

	Pass a converter function to filter and/or mutate the events as they
	are imported. It will be given a raw dictionary of event info, and
	may mutate it in any way (notably, the "summary" and "description").
	If it returns True, the event will be imported, otherwise skipped.
	"""
	# Step 1: List all events in the target calendar. Purge any that are
	# obvious duplicates or have no recognized source.
	if to_cal not in purgeme:
		old_events = purgeme[to_cal] = {}
		# Check events up to a day earlier than we're mainly working. Otherwise,
		# timezones and all-day events can wreak havoc with us. TODO: See if the
		# upshot is that week-old events get deleted, which wouldn't be ideal.
		for ts, desc, raw in upcoming_events(to_cal, days=days+1, offset=-86400, include_all_day=True):
			src = raw.get("source", {})
			url = src.get("url", "")
			if purge or not url or url in old_events:
				print("Deleting", raw["summary"])
				service.events().delete(calendarId=to_cal, eventId=raw["id"]).execute()
				continue
			old_events[url] = src.get("title", ""), raw["id"]
	else:
		old_events = purgeme[to_cal]

	# Step 2: Fetch events from the source calendar. Any that we already
	# have, accept and move on; otherwise create new events.
	for ts, desc, raw in upcoming_events(from_cal, days=days, include_all_day=True):
		src, tag = raw["htmlLink"], raw["etag"]
		if not convert(raw): continue # Note that 'raw' could be mutated here
		if src in old_events:
			# Check if the event is absolutely identical. If so, skip;
			# otherwise, delete the old one and replace it. Note that
			# if the filtration/mapping function is changed, the etag
			# check won't be valid. If that happens, use --purge to
			# force all events to be removed and recreated.
			if old_events[src][0] == raw["etag"]:
				del old_events[src]
				continue
		new_ev = {key: raw[key] for key in "summary description start end colorId".split() if key in raw}
		new_ev["source"] = {"url": src, "title": tag}
		print("Migrating", raw["summary"])
		ev = service.events().insert(calendarId=to_cal, body=new_ev).execute()

	# Step 3: Remove all events that weren't accepted in step 2.
	# Done externally.

@command
@kwoargs("purge")
def auto_migrate(purge=False):
	"""Perform all the auto-migrations specified in keys.py"""
	if not AUTO_MIGRATE:
		return "No auto migrations specified"
	auth()
	purgeme = {}
	from googleapiclient.http import HttpError
	for spec in AUTO_MIGRATE:
		try:
			migrate(purgeme, *spec, purge=purge)
		except HttpError as e:
			print("Unable to automigrate:", e)
			# It can be retried later.
	for to_cal, old_events in purgeme.items():
		if old_events: print("Cleaning up old events on", to_cal)
		for tag, id in old_events.values():
			print("Deleting", id)
			service.events().delete(calendarId=to_cal, eventId=id).execute()

@command
def color_demo():
	auth()
	for color in range(12):
		new_ev = {
			"colorId": color + 12,
			"summary": "Color %d" % color,
			"start": {"dateTime": "2018-10-28T%02d:00:00-08:00" % (color,), "timeZone": "Australia/Melbourne"},
			"end": {"dateTime": "2018-10-28T%02d:00:00-08:00" % (color+1,), "timeZone": "Australia/Melbourne"},
		}
		ev = service.events().insert(calendarId="4p6lkis01le8tgsjvkm0p33mkc@group.calendar.google.com", body=new_ev).execute()
		print(ev)

def set_title(title):
	print("\033]0;"+title, end="\a")
	sys.stdout.flush()

def pick_random_file():
	"""Like random.choice(os.listdir(ALERT_DIR)) but respects the weights file"""
	# Returns a native string - bytes on Py2, text on Py3.
	files = dict.fromkeys(os.listdir(ALERT_DIR), 1)
	try:
		with open("weights") as f:
			for line in f:
				if ':' not in line: continue
				if line.strip().startswith('#'): continue
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
	c = Counter(pick_random_file() for _ in range(numfiles))
	for fn, count in sorted(c.items(), key=lambda item: -item[1]):
		print(count, fn)

@command
def play_alert():
	"""Play an alert immediately"""
	fn = pick_random_file()
	print(fn)
	subprocess.Popen(["vlc",os.path.join(ALERT_DIR,fn)],stdout=open(os.devnull,"wb"),stderr=subprocess.STDOUT).wait()

@command
@kwoargs("offset", "days", "title", "auto_import")
def wait(calendar=DEFAULT_CALENDAR, offset=0, days=7, title=False, auto_import=0):
	"""Await the next event on this calendar
	
	calendar: Calendar ID, as shown by list()

	offset: Number of seconds leeway, eg 300 to halt 5 mins before

	days: Number of days in the future to look - gives up if no events in that time

	title: Set the terminal title to show what's happening

	auto_import: Approximate period (in seconds) to rerun an autoimport
	"""
	auth()
	from googleapiclient.http import HttpError
	offset, days = int(offset), int(days)
	prev = None
	next_auto_import = 0
	while True:
		now = datetime.datetime.now(pytz.utc)
		try:
			events = upcoming_events(calendar, offset, days)

			if auto_import and time() > next_auto_import:
				auto_migrate()
				next_auto_import = time() + auto_import
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

		tm, event, _ = events[0]
		target = tm - datetime.timedelta(seconds=offset)
		delay = target - datetime.datetime.now(pytz.utc)
		if prev and prev != event: print() # Drop to a new line if the target event changes
		print("Sleeping", delay, "until", target, "-" , event, end="\33[K\r")
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
			print()
			if title: set_title("!! " + event)
			play_alert()
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
		# Attempt to fire an alarm sound. If it fails, so be it; we already have the log.
		subprocess.Popen(["vlc", "alarm.mp3"], stdout=open(os.devnull,"wb"), stderr=subprocess.STDOUT).wait()
		raise
