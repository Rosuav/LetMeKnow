"""DocstringArgs demo"""
from docstringargs import DocstringArgs

cmdline = DocstringArgs(__doc__)

@cmdline
def hello(where: "Where to say hello to"="world"):
	"""Say hello to somewhere"""
	print("Hello, %s!"%where)

@cmdline
def count(top=5):
	"""Count from 1, human style

	top: Number to count up to"""
	for i in range(1, int(top)+1): print(i)

arguments = cmdline.parse_args()
globals()[arguments.pop("command")](**arguments)
