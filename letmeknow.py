from __future__ import print_function
import sys
import argparse

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
	doc = f.__doc__
	if not doc: doc=""
	doc = doc.split("\n")
	p = subparsers.add_parser(f.__name__, help=doc[0])
	for arg in doc[1:]:
		arg = arg.strip().split(":", 1)
		if len(arg) < 2: continue # Blank lines etc
		p.add_argument(arg[0].strip(), help=arg[1].strip())
	return f

@command
def list():
	"""List calendars available to your account"""
	page_token = None
	while True:
		calendar_list = service.calendarList().list(pageToken=page_token).execute()
		for calendar_list_entry in calendar_list['items']:
			print(calendar_list_entry['summary'])
		page_token = calendar_list.get('nextPageToken')
		if not page_token: break

if __name__ == "__main__":
	arguments = parser.parse_args(sys.argv[1:]).__dict__
	auth()
	globals()[arguments.pop("command")](**arguments)
