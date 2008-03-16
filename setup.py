#!/usr/bin/env python
try:
	from sugar.activity import bundlebuilder
	bundlebuilder.start("moon")
except ImportError:
	import os
	os.system("find ./ | sed 's,^./,Moon.activity/,g' | sed 's,//,/,g' | grep -v /.git > MANIFEST")
	os.system('rm Moon.xo')
	os.chdir('..')
	os.system('zip -r Moon.xo Moon.activity -x \*/.git\*')
	os.system('mv Moon.xo ./Moon.activity')
	os.chdir('Moon.activity')
