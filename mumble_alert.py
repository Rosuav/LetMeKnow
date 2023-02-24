import os
import socket
import struct
import subprocess
import time
import letmeknow

HOST = "localhost"
PORT = 64738

def fire_alert():
	# Basically the same as letmeknow.play_alert() but asynchronous
	fn = letmeknow.pick_random_file()
	subprocess.Popen(["vlc", os.path.join(letmeknow.ALERT_DIR,fn)], stdout=open(os.devnull,"wb"), stderr=subprocess.STDOUT)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1)

last_users = None

while True:
	# The sent message is four bytes of zeros followed by an eight byte
	# identifier. We're using all zero for simplicity.
	sock.sendto(bytes(12), (HOST, PORT))
	data, addr = sock.recvfrom(1024) # Will raise on timeout
	# See protocol details at https://wiki.mumble.info/wiki/Protocol
	ver, ident, users, maxusers, maxbw = struct.unpack(">iQiii", data)
	# print(hex(ver), ident, users, maxusers, maxbw)
	if users != last_users and last_users is not None:
		print("Formerly %d users, now %d" % (last_users, users))
		if users > last_users: fire_alert()
	last_users = users
	time.sleep(3) # Fairly frequent polls, but hey, it's a simple UDP query
