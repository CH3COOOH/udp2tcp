DEBUG = False

def set_debug(enabled):
	global DEBUG
	DEBUG = bool(enabled)


def debug(msg):
	if DEBUG:
		print(msg)