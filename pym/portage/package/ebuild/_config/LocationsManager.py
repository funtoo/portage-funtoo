# Copyright 2010 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2

__all__ = (
	'LocationsManager',
)

import codecs
from portage import os, eapi_is_supported, _encodings, _unicode_encode
from portage.const import CUSTOM_PROFILE_PATH, GLOBAL_CONFIG_PATH, \
	PROFILE_PATH, USER_CONFIG_PATH
from portage.exception import DirectoryNotFound, ParseError
from portage.localization import _
from portage.util import ensure_dirs, grabfile, \
	normalize_path, shlex_split, writemsg


class LocationsManager(object):

	def __init__(self, config_root=None, eprefix=None, config_profile_path=None, local_config=True, \
		target_root=None):
		self.user_profile_dir = None
		self._local_repo_conf_path = None
		self.eprefix = eprefix
		self.config_root = config_root
		self.target_root = target_root
		self._user_config = local_config
		
		if self.eprefix is None:
			self.eprefix = ""

		if self.config_root is None:
			self.config_root = self.eprefix + os.sep

		self.config_root = normalize_path(os.path.abspath(self.config_root)).rstrip(os.path.sep) + os.path.sep

		# make sure config_root, ie. "/etc", is a directory. If not, complain to the user about the value of "PORTAGE_CONFIGROOT":

		self._check_directory("PORTAGE_CONFIGROOT", self.config_root)

		# set abs_user_config to "/etc/portage":

		self.abs_user_config = os.path.join(self.config_root, USER_CONFIG_PATH)

		if config_profile_path is None:
			# if repoman didn't passing config_profile_path of "", then set the profile path ourselves...
			config_profile_path = os.path.join(self.config_root, PROFILE_PATH)
			# is /etc/make.profile a directory?:
			if os.path.isdir(config_profile_path):
				# yes - ok, use it. The "classic" approach.
				self.profile_path = config_profile_path
			else:
				# no? look for /etc/portage/make.profile:
				config_profile_path = \
					os.path.join(self.abs_user_config, 'make.profile')
				# is /etc/portage/make.profile a directory?
				if os.path.isdir(config_profile_path):
					# yes - ok, treat /etc/portage/make.profile as an alternative to traditional /etc/make.profile:
					self.profile_path = config_profile_path
				else:
					# no - hrm. We don't have a profile directory then!
					self.profile_path = None
		else:
			# NOTE: repoman may pass in an empty string here, in order to create an empty profile  for checking dependencies of packages with empty KEYWORDS.
			self.profile_path = config_profile_path

		# create a list of all our profiles - this recursively iterates through cascading profiles and makes a list of all  of 'em:

		self.profiles = []

		# do we have a profile directory?:
		if self.profile_path:
			# yes - ok, try grabbing profiles:
			try:
				# this does the recursive heavy lifting of looking at "parent" files and creating a list of profiles in self.profiles:
				self._addProfile(os.path.realpath(self.profile_path))
			except ParseError as e:
				# ugh - there was some error recursively parsing the profile...
				writemsg(_("!!! Unable to parse profile: '%s'\n") % \
					self.profile_path, noiselevel=-1)
				writemsg("!!! ParseError: %s\n" % str(e), noiselevel=-1)
				self.profiles = []

		# we have a list of all our cascading profiles. Now we want to see if we have an /etc/portage/profile directory.

		if self._user_config and self.profiles:
			# /etc/portage/profile:
			custom_prof = os.path.join(self.config_root, CUSTOM_PROFILE_PATH)
			if os.path.exists(custom_prof):
				# /etc/portage/profile exists! so let's tag it at the end of our cascaded profiles then.
				self.user_profile_dir = custom_prof
				self.profiles.append(custom_prof)
			del custom_prof

		# ok, we now have a list of all our profiles - convert them from mutable list to immutable tuple. We're done:

		self.profiles = tuple(self.profiles)

	def _check_directory(self, varname, var):
		if not os.path.isdir(var):
			writemsg(_("!!! Error: %s='%s' is not a directory. " "Please correct this.\n") % (varname, var), noiselevel=-1)
			raise DirectoryNotFound(var)

	def _addProfile(self, currentPath):

		# _addProfile implements the "cascading" profile support in Portage by recursively iterating through profiles and
		# creating a list of all referenced profiles in self.profiles.

		# self.profiles is evaluated from beginning to end, so the first profile in the list is the top parent profile, but
		# its values can get overridden by the profiles that follow it.

		# define locations for "parents" and "EAPI" files:
		
		parentsFile = os.path.join(currentPath, "parent")
		eapi_file = os.path.join(currentPath, "eapi")

	
		# if eapi file exists, try to open it. If IOError, just continue. But if we open it and the EAPI listed isn't supported,
		# then throw an error:

		if os.path.exists(eapi_file):
			try:
				eapi = codecs.open(_unicode_encode(eapi_file, encoding=_encodings['fs'], errors='strict'), mode='r', encoding=_encodings['content'], errors='replace').readline().strip()
			except IOError:
				pass
			else:
				if not eapi_is_supported(eapi):
					raise ParseError(_( "Profile contains unsupported " "EAPI '%s': '%s'") % (eapi, os.path.realpath(eapi_file),))

		# Does the parents file exist in this profile? If so, grab its contents:

		if os.path.exists(parentsFile):
			
			parents = grabfile(parentsFile)
		
			# If the file was empty, throw an error:

			if not parents:
				raise ParseError( _("Empty parent file: '%s'") % parentsFile)
			
			# For each line in the parents file, use the line as a relative path to modify "currentPath", our current path:

			for parentPath in parents:
				parentPath = normalize_path(os.path.join(currentPath, parentPath))

				# if this path exists, recursively add this profile (recursive call):

				if os.path.exists(parentPath):
					self._addProfile(parentPath)
				else:
					raise ParseError( _("Parent '%s' not found: '%s'") % (parentPath, parentsFile))

		# after recursively processing parents, add our own profile to the list:

		self.profiles.append(currentPath)

	def set_root_override(self, root_override=None):
	
		# This method is used to set the self.target_root, self.eroot and self.global_config_path variables.
		# These are used by pym/portage/package/ebuild/config.py to define these settings for portage.

		# root_override is the value of ROOT that comes from /etc/make.conf. 
		
		# if target_root isn't defined, and root_override is specified, then use root_override as self.target_root:

		if self.target_root is None and root_override is not None:
			self.target_root = root_override
			if not self.target_root.strip():
				self.target_root = None

		# if target_root is still None, default to "/":

		if self.target_root is None:
			self.target_root = "/"

		# normalize the path of target_root and ensure it ends with the OS path separator (ie. "/"):

		self.target_root = normalize_path(os.path.abspath(self.target_root)).rstrip(os.path.sep) + os.path.sep

		# ensure_dirs will create target_root if it doesn't exists, and ensure it has proper perms:
		
		ensure_dirs(self.target_root)
		
		# make sure self.target_root is a directory, otherwise complain to the user abou their ROOT variable:

		self._check_directory("ROOT", self.target_root)

		# set self.eroot to self.target_root + self.eprefix + "/" (eprefix is typically "")

		self.eroot = self.target_root.rstrip(os.sep) + self.eprefix + os.sep

		# set global_config_path (the path where Portage will look for make.globals) relative to eprefix if it is defined:	

		self.global_config_path = os.path.join(self.eprefix, GLOBAL_CONFIG_PATH)

	def set_profile_dirs(self, portdir, portdir_overlay):

		# This method defines the location of the profile directories.

		# we are passed the PORTDIR and PORTDIR_OVERLAY values as arguments:

		if portdir_overlay is None:
			portdir_overlay = ""

		self.overlay_profiles = []

		# for each overlay listed in PORTDIR_OVERLAY:

		for ov in shlex_split(portdir_overlay):
			ov = normalize_path(ov)
			profiles_dir = os.path.join(ov, "profiles")

			# if the overlay has a "/profiles" directory in it, then add it to self.overlay_profiles:

			if os.path.isdir(profiles_dir):
				self.overlay_profiles.append(profiles_dir)

		# define self.profile_locations to include the location of our main profile in PORTDIR/profiles plus all our overlay profiles:

		self.profile_locations = [os.path.join(portdir, "profiles")] + self.overlay_profiles
	
		# define self.profile_and_user_locations to contain the profile_locations list, plus optionally /etc/portage/profile if it exists:

		self.profile_and_user_locations = self.profile_locations[:]
		if self._user_config:
			self.profile_and_user_locations.append(self.abs_user_config)

		# convert everything to read-only tuples:

		self.profile_locations = tuple(self.profile_locations)
		self.profile_and_user_locations = tuple(self.profile_and_user_locations)

		# pym/portage/package/ebuild/config.py uses both these aoove ^^ when it does its thing
