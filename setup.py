#!/usr/bin/env python
try:
	from sugar.activity import bundlebuilder
	bundlebuilder.start("moon")
except ImportError:
	import os
	os.system("find ./ | sed 's,^./,Moon.activity/,g' > MANIFEST")
	os.system('rm Moon.xo')
	os.chdir('..')
	os.system('zip -r Moon.xo Moon.activity')
	os.system('mv Moon.xo ./Moon.activity')
	os.chdir('Moon.activity')
