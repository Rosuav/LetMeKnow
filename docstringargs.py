import argparse

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
