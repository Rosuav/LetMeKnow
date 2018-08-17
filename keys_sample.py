# Copy this file to keys.py and enter the appropriate keys as assigned by Google.
# Go to https://console.developers.google.com/ and create an app, then enable the
# Google Calendar API for it. Obtain OAuth2 credentials and record them here.
CLIENT_ID = ""
CLIENT_SECRET = ""
DEFAULT_CALENDAR = "" # If nonblank, will be the default for all 'calendar' args
ALERT_DIR = "" # If nonblank, a file from this directory will be picked at random and passed to VLC
ALERT_REPEAT = False # If True, alerting will be done in 'repeat' mode. Not useful if ALERT_DIR unset.
READ_ONLY = True # Set to False if you want to use the 'migrate' subcommand; True requests smaller OAuth scope
AUTO_MIGRATE = [
	# Define default migrations here:
	# source, destination, filter (or map), days ahead to look
	# ('from_calendar', 'to_calendar'),
	# ('from_other_cal', 'to_calendar', lambda info: "dateTime" in info["start"]),
	# ('another_source', 'another_dest', lambda info: True, 90),
]
