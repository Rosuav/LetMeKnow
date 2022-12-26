#!/usr/local/bin/python3.11
import os
import getpass
import subprocess
import pymumble_py3
import letmeknow
m = pymumble_py3.Mumble("localhost", "notifier", password=getpass.getpass()) 
m.start() # Start before setting up the callbacks. We don't need a notification for people already present.
m.is_ready()

def callback(cb):
	def deco(func):
		m.callbacks.add_callback(cb, func)
		return func
	return deco

def fire_alert():
	# Basically the same as letmeknow.play_alert() but asynchronous
	fn = letmeknow.pick_random_file()
	subprocess.Popen(["vlc", os.path.join(letmeknow.ALERT_DIR,fn)], stdout=open(os.devnull,"wb"), stderr=subprocess.STDOUT)

@callback(pymumble_py3.callbacks.PYMUMBLE_CLBK_USERCREATED)
def user_arrived(user):
	print("USER ARRIVED:", user["name"])
	fire_alert()

m.join()
