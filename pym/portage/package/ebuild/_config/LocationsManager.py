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
			writemsg(_("!!! Error: %s='%s' is not a directory. "
				"Please correct this.\n") % (varname, var),
				noiselevel=-1)
			raise DirectoryNotFound(var)

	def _addProfile(self, currentPath):
		parentsFile = os.path.join(currentPath, "parent")
		eapi_file = os.path.join(currentPath, "eapi")
		try:
			eapi = codecs.open(_unicode_encode(eapi_file,
				encoding=_encodings['fs'], errors='strict'),
				mode='r', encoding=_encodings['content'], errors='replace'
				).readline().strip()
		except IOError:
			pass
		else:
			if not eapi_is_supported(eapi):
				raise ParseError(_(
					"Profile contains unsupported "
					"EAPI '%s': '%s'") % \
					(eapi, os.path.realpath(eapi_file),))
		if os.path.exists(parentsFile):
			parents = grabfile(parentsFile)
			if not parents:
				raise ParseError(
					_("Empty parent file: '%s'") % parentsFile)
			for parentPath in parents:
				parentPath = normalize_path(os.path.join(
					currentPath, parentPath))
				if os.path.exists(parentPath):
					self._addProfile(parentPath)
				else:
					raise ParseError(
						_("Parent '%s' not found: '%s'") %  \
						(parentPath, parentsFile))
		self.profiles.append(currentPath)

	def set_root_override(self, root_overwrite=None):
		# Allow ROOT setting to come from make.conf if it's not overridden
		# by the constructor argument (from the calling environment).
		if self.target_root is None and root_overwrite is not None:
			self.target_root = root_overwrite
			if not self.target_root.strip():
				self.target_root = None
		if self.target_root is None:
			self.target_root = "/"

		self.target_root = normalize_path(os.path.abspath(
			self.target_root)).rstrip(os.path.sep) + os.path.sep

		ensure_dirs(self.target_root)
		self._check_directory("ROOT", self.target_root)

		self.eroot = self.target_root.rstrip(os.sep) + self.eprefix + os.sep

		# make.globals should not be relative to config_root
		# because it only contains constants. However, if EPREFIX
		# is set then there are two possible scenarios:
		# 1) If $ROOT == "/" then make.globals should be
		#    relative to EPREFIX.
		# 2) If $ROOT != "/" then the correct location of
		#    make.globals needs to be specified in the constructor
		#    parameters, since it's a property of the host system
		#    (and the current config represents the target system).
		self.global_config_path = GLOBAL_CONFIG_PATH
		if self.eprefix:
			if self.target_root == "/":
				# case (1) above
				self.global_config_path = os.path.join(self.eprefix,
					GLOBAL_CONFIG_PATH.lstrip(os.sep))
			else:
				# case (2) above
				# For now, just assume make.globals is relative
				# to EPREFIX.
				# TODO: Pass in more info to the constructor,
				# so we know the host system configuration.
				self.global_config_path = os.path.join(self.eprefix,
					GLOBAL_CONFIG_PATH.lstrip(os.sep))

	def set_port_dirs(self, portdir, portdir_overlay):
		self.portdir = portdir
		self.portdir_overlay = portdir_overlay
		if self.portdir_overlay is None:
			self.portdir_overlay = ""

		self.overlay_profiles = []
		for ov in shlex_split(self.portdir_overlay):
			ov = normalize_path(ov)
			profiles_dir = os.path.join(ov, "profiles")
			if os.path.isdir(profiles_dir):
				self.overlay_profiles.append(profiles_dir)

		self.profile_locations = [os.path.join(portdir, "profiles")] + self.overlay_profiles
		self.profile_and_user_locations = self.profile_locations[:]
		if self._user_config:
			self.profile_and_user_locations.append(self.abs_user_config)

		self.profile_locations = tuple(self.profile_locations)
		self.profile_and_user_locations = tuple(self.profile_and_user_locations)
