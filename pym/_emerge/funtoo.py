def action_sync(settings, trees, mtimedb, myopts, myaction):
	enter_invalid = '--ask-enter-invalid' in myopts
	xterm_titles = "notitles" not in settings.features
	emergelog(xterm_titles, " === sync")
	portdb = trees[settings["ROOT"]]["porttree"].dbapi
	myportdir = portdb.porttree_root
	if not myportdir:
		myportdir = settings.get('PORTDIR', '')
		if myportdir and myportdir.strip():
			myportdir = os.path.realpath(myportdir)
		else:
			myportdir = None
	out = portage.output.EOutput()
	global_config_path = GLOBAL_CONFIG_PATH
	if settings['EPREFIX']:
		global_config_path = os.path.join(settings['EPREFIX'],
				GLOBAL_CONFIG_PATH.lstrip(os.sep))
	if not myportdir:
		sys.stderr.write("!!! PORTDIR is undefined. Is %s/make.globals missing?\n" % global_config_path)
		sys.exit(1)
	if myportdir[-1]=="/":
		myportdir=myportdir[:-1]
	try:
		st = os.stat(myportdir)
	except OSError:
		st = None

	syncuri = settings.get("SYNC", "").strip()
	syncuser = settings.get("SYNC_USER", "root").strip()
	syncumask = settings.get("SYNC_UMASK", "022").strip()
	updatecache_flg = False
	if myaction == "metadata":
		print("skipping sync")
		updatecache_flg = True
	if portage.process.find_binary("git") is None:
		msg = ["Command not found: git", "Type \"emerge dev-vcs/git\" to enable git support."]
		for l in msg:
			writemsg_level("!!! %s\n" % l, level=logging.ERROR, noiselevel=-1)
		return 1
	updatecache_flg = True
	if not os.path.exists(myportdir):
		if not syncuri:
			writemsg_level("SYNC is undefined.\nPlease set SYNC to the remote location of the Portage repository.\n", noiselevel=-1, level=logging.ERROR)
			return 1


		# A few tricks are required to get git cloning by a non-root user. We will create a temporary working directory called work_path
		# (/usr/portage.sync). We will make sure this directory is owned by the SYNC_USER user, and then we will use "su" to run git clone
		# inside this directory, so that git can create the initial repository directory with the proper user permissiosn. After git
		# clone completes, we will move our new portage tree in repo_path_tmp to repo_path_fin, its final location. And then we will remove
		# work_path, our temporary directory.

		# common_path = /usr
		# repo_dir = portage
		# work_path = /usr/portage.sync
		# repo_path_tmp = /usr/portage.sync/portage
		# repo_path_fin = /usr/portage

		common_path = os.path.dirname(myportdir)
		repo_dir = os.path.basename(myportdir)
		work_path = os.path.join(common_path, repo_dir + ".sync")
		repo_path_tmp = os.path.join(work_path, repo_dir)
		repo_path_fin = os.path.join(common_path, repo_dir)
			
		print(">>> Using %s as temporary clone directory..." % repo_path_tmp)

		# if the directories we will be using exist, try to remove them, non-recursively. If that doesn't work, there are files in them
		# and throw an error message, requesting the user remove these files so that sync can proceed.

		for checkdir in [ repo_path_tmp, work_path ]:
			if os.path.exists(checkdir):
				try:
					os.rmdir(checkdir)
				except OSError as e:
					print("!!! %s exists and contains files. Please remove so that clone can proceed." % checkdir )
					sys.exit(1)

		# at this point, we want to create an initial portage.sync directory, owned by the user, into which we can use su to run git as
		# the user, and create the new portage tree directory owned by the user.

		if not os.path.exists(common_path):
			# create common path directory, ie. /var/git, if it doesn't exist.
			os.makedirs(common_path)

		if portage.process.spawn_bash("cd %s && umask %s && install -d -o %s %s" % ( common_path, syncumask, syncuser, work_path)) != os.EX_OK:
			print("!!! Unable to create initial sync directory %s; exiting." % work_path)
			sys.exit(1)

		# We've created our temporary work directory, but is the final location actually reachable - ie. readable, by SYNC_USER? We'll
		# find out now.

		if portage.process.spawn_bash("su - %s -s /bin/sh -c 'cd %s'" % ( syncuser, common_path )) != os.EX_OK:
			print("!!! Path %s is not reachable by user %s; please adjust permissions or SYNC_USER setting to correct." %  ( common_path, syncuser ))
			sys.exit(1)

		# Everything looks OK, so now we will clone the repository:
		
		print(">>> Starting initial git clone with "+syncuri+"...")

		if portage.process.spawn_bash("su - %s -s /bin/sh -c 'umask %s && cd %s && exec git clone %s %s && mv '" % (syncuser, syncumask, work_path, portage._shell_quote(syncuri), repo_dir)) != os.EX_OK:
			print("!!! git clone error; exiting.")
			sys.exit(1)
		
		# Our clone should now exist in the temporary location, now move it to the final location, as root:

		if portage.process.spawn_bash("mv %s %s" % (repo_path_tmp, repo_path_fin)) != os.EX_OK:
			print("!!! Couldn't move %s into final location %s; exiting." % ( repo_path_tmp, repo_path_fin ))
			sys.exit(1)

		# Clean up after ourselves:
		portage.process.spawn_bash("rm -rf %s" % (repo_path_tmp))
	else:
		if not os.path.exists(myportdir+"/.git"):
			print("!!! Portage tree at %s does not appear to be a git repository. Please move out of the way or correct your PORTDIR setting and retry." % myportdir)
			sys.exit(1)
		if portage.process.spawn_bash("su - %s -s /bin/sh -c 'cd %s >/dev/null 2>&1'" % ( syncuser, myportdir )) != os.EX_OK:
			print("!!! Portage tree at %s is not reachable by user %s; please adjust permissions to correct." %  ( myportdir, syncuser ))
			sys.exit(1)
		print(">>> Starting git pull...")
		exitcode = portage.process.spawn_bash( "su - %s -s /bin/sh -c 'umask %s && cd %s && exec git pull --no-stat'" % (syncuser, syncumask, portage._shell_quote(myportdir),))
		if exitcode != os.EX_OK:
			msg = "!!! git pull error in %s." % myportdir
			emergelog(xterm_titles, msg)
			writemsg_level(msg + "\n", level=logging.ERROR, noiselevel=-1)
			return exitcode
		msg = ">>> Git pull in %s successful" % myportdir
		emergelog(xterm_titles, msg)
		writemsg_level(msg + "\n")

	# if initial clone or sync, 
	exitcode = git_sync_timestamps(settings, myportdir)
	if exitcode != os.EX_OK:
		sys.exit(retval)

	if updatecache_flg and myaction != "metadata" and "metadata-transfer" not in settings.features:
		updatecache_flg = False

	# Reload the whole config from scratch.
	settings, trees, mtimedb = load_emerge_config(trees=trees)
	adjust_configs(myopts, trees)
	root_config = trees[settings["ROOT"]]["root_config"]
	portdb = trees[settings["ROOT"]]["porttree"].dbapi

	if updatecache_flg and os.path.exists(os.path.join(myportdir, 'metadata', 'cache')):

		# Only update cache for myportdir since that's
		# the only one that's been synced here.
		action_metadata(settings, portdb, myopts, porttrees=[myportdir])

	if myopts.get('--package-moves') != 'n' and _global_updates(trees, mtimedb["updates"], quiet=("--quiet" in myopts)):
		mtimedb.commit()
		# Reload the whole config from scratch.
		settings, trees, mtimedb = load_emerge_config(trees=trees)
		adjust_configs(myopts, trees)
		portdb = trees[settings["ROOT"]]["porttree"].dbapi
		root_config = trees[settings["ROOT"]]["root_config"]

	chk_updated_cfg_files(settings["EROOT"], portage.util.shlex_split(settings.get("CONFIG_PROTECT", "")))

	if myaction != "metadata":
		postsync = os.path.join(settings["PORTAGE_CONFIGROOT"], portage.USER_CONFIG_PATH, "bin", "post_sync")
		if os.access(postsync, os.X_OK):
			retval = portage.process.spawn( [postsync, syncuri], env=settings.environ())
			if retval != os.EX_OK:
				print(red(" * ") + bold("spawn failed of " + postsync))

	display_news_notification(root_config, myopts)
	return os.EX_OK

def action_uninstall(settings, trees, ldpath_mtimes,
	opts, action, files, spinner):

	# For backward compat, some actions do not require leading '='.
	ignore_missing_eq = action in ('clean', 'unmerge')
	root = settings['ROOT']
	vardb = trees[root]['vartree'].dbapi
	valid_atoms = []
	lookup_owners = []

	# Ensure atoms are valid before calling unmerge().
	# For backward compat, leading '=' is not required.
	for x in files:
		if is_valid_package_atom(x, allow_repo=True) or \
			(ignore_missing_eq and is_valid_package_atom('=' + x)):

			try:
				valid_atoms.append(
					dep_expand(x, mydb=vardb, settings=settings))
			except portage.exception.AmbiguousPackageName as e:
				msg = "The short ebuild name \"" + x + \
					"\" is ambiguous.  Please specify " + \
					"one of the following " + \
					"fully-qualified ebuild names instead:"
				for line in textwrap.wrap(msg, 70):
					writemsg_level("!!! %s\n" % (line,),
						level=logging.ERROR, noiselevel=-1)
				for i in e.args[0]:
					writemsg_level("    %s\n" % colorize("INFORM", i),
						level=logging.ERROR, noiselevel=-1)
				writemsg_level("\n", level=logging.ERROR, noiselevel=-1)
				return 1

		elif x.startswith(os.sep):
			if not x.startswith(root):
				writemsg_level(("!!! '%s' does not start with" + \
					" $ROOT.\n") % x, level=logging.ERROR, noiselevel=-1)
				return 1
			# Queue these up since it's most efficient to handle
			# multiple files in a single iter_owners() call.
			lookup_owners.append(x)

		elif x.startswith(SETPREFIX) and action == "deselect":
			valid_atoms.append(x)

		else:
			msg = []
			msg.append("'%s' is not a valid package atom." % (x,))
			msg.append("Please check ebuild(5) for full details.")
			writemsg_level("".join("!!! %s\n" % line for line in msg),
				level=logging.ERROR, noiselevel=-1)
			return 1

	if lookup_owners:
		relative_paths = []
		search_for_multiple = False
		if len(lookup_owners) > 1:
			search_for_multiple = True

		for x in lookup_owners:
			if not search_for_multiple and os.path.isdir(x):
				search_for_multiple = True
			relative_paths.append(x[len(root)-1:])

		owners = set()
		for pkg, relative_path in \
			vardb._owners.iter_owners(relative_paths):
			owners.add(pkg.mycpv)
			if not search_for_multiple:
				break

		if owners:
			for cpv in owners:
				slot = vardb.aux_get(cpv, ['SLOT'])[0]
				if not slot:
					# portage now masks packages with missing slot, but it's
					# possible that one was installed by an older version
					atom = portage.cpv_getkey(cpv)
				else:
					atom = '%s:%s' % (portage.cpv_getkey(cpv), slot)
				valid_atoms.append(portage.dep.Atom(atom))
		else:
			writemsg_level(("!!! '%s' is not claimed " + \
				"by any package.\n") % lookup_owners[0],
				level=logging.WARNING, noiselevel=-1)

	if files and not valid_atoms:
		return 1

	if action == 'unmerge' and \
		'--quiet' not in opts and \
		'--quiet-unmerge-warn' not in opts:
		msg = "This action can remove important packages! " + \
			"In order to be safer, use " + \
			"`emerge -pv --depclean <atom>` to check for " + \
			"reverse dependencies before removing packages."
		out = portage.output.EOutput()
		for line in textwrap.wrap(msg, 72):
			out.ewarn(line)

	if action == 'deselect':
		return action_deselect(settings, trees, opts, valid_atoms)

	# Create a Scheduler for calls to unmerge(), in order to cause
	# redirection of ebuild phase output to logs as required for
	# options such as --quiet.
	sched = Scheduler(settings, trees, None, opts,
		spinner)
	sched._background = sched._background_mode()
	sched._status_display.quiet = True

	if action in ('clean', 'unmerge') or \
		(action == 'prune' and "--nodeps" in opts):
		# When given a list of atoms, unmerge them in the order given.
		ordered = action == 'unmerge'
		unmerge(trees[settings["ROOT"]]['root_config'], opts, action,
			valid_atoms, ldpath_mtimes, ordered=ordered,
			scheduler=sched._sched_iface)
		rval = os.EX_OK
	else:
		rval = action_depclean(settings, trees, ldpath_mtimes,
			opts, action, valid_atoms, spinner, scheduler=sched._sched_iface)

	return rval

def pw_grp_conv(eroot):
	if eroot != "/":
		return
	if os.path.exists("/usr/sbin/pwconv"):
		portage.process.spawn_bash("/usr/sbin/pwconv")
	if os.path.exists("/usr/sbin/grpconv"):
		portage.process.spawn_bash("/usr/sbin/grpconv")
	

