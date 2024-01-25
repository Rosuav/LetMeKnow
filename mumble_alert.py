import os
import socket
import struct
import subprocess
import time
import letmeknow

HOST = "localhost"
PORT = 64738
POLLDELAY = 3 # Fairly frequent polls, but hey, it's a simple UDP query

def fire_alert():
	# Basically the same as letmeknow.play_alert() but asynchronous
	fn = letmeknow.pick_random_file()
	subprocess.Popen(["vlc", os.path.join(letmeknow.ALERT_DIR,fn)], stdout=open(os.devnull,"wb"), stderr=subprocess.STDOUT)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1)

last_users = None
alert_users = None

while True:
	# The sent message is four bytes of zeros followed by an eight byte
	# identifier. We're using all zero for simplicity.
	sock.sendto(bytes(12), (HOST, PORT))
	data, addr = sock.recvfrom(1024) # Will raise on timeout
	# See protocol details at https://wiki.mumble.info/wiki/Protocol
	ver, ident, users, maxusers, maxbw = struct.unpack(">iQiii", data)
	# print(hex(ver), ident, users, maxusers, maxbw)
	if users != last_users:
		if last_users is not None:
			print("Formerly %d users [for %ds], now %d" % (last_users, last_users_count * POLLDELAY, users))
			if alert_users is None and users > last_users: alert_users = users
		else:
			print(f"Online: {users} / {maxusers}")
		last_users_count = 0
	last_users = users
	last_users_count += 1
	if last_users_count > 2 and alert_users is not None:
		# Only fire an alert if we remain above the previous for a couple of checks
		if alert_users == users: fire_alert()
		alert_users = None
	time.sleep(POLLDELAY)
