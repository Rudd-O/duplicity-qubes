# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# This file is NOT part of duplicity.  It is an extension to Duplicity
# that allows the Qubes OS dom0 to back up to a Qubes OS VM.
#
# Duplicity is free software, and so is this file.  This file is
# under the same license as the one distributed by Duplicity.

import io
import os
import pipes
import subprocess

import duplicity.backend
from duplicity import log, progress
from duplicity.errors import *

BLOCKSIZE = 1048576  # for doing file transfers by chunk
MAX_LIST_SIZE = 10485760  # limited to 10 MB directory listings to avoid problems


class QubesVMBackend(duplicity.backend.Backend):
    """This backend accesses files stored on a Qubes OS VM.  It is intended to
    work as a backed within a Qubes OS dom0 (TCB) for the purposes of using
    Duplicity to back up to a VM.  No special tools are required other than
    this backend file itself installed to your Duplicity backends directory.

    Missing directories on the remote (VM) side will NOT be created.  It is
    an error to try and back up to a VM when the target directory does
    not already exist.

    module URL: qubesvm://vmname/path/to/backup/directory
    """
    def __init__(self, parsed_url):
        properly_parsed_url = parsed_url
        duplicity.backend.Backend.__init__(self, properly_parsed_url)
        if properly_parsed_url.path:
            self.remote_dir = properly_parsed_url.path
        else:
            self.remote_dir = '.'
        self.hostname = properly_parsed_url.hostname

    def _validate_remote_filename(self, op, remote_filename):
        if os.path.sep in remote_filename or "\0" in remote_filename:
            raise BackendException(
                ("Qubes VM %s failed: path separators "
                 "or nulls in destination file name %s") % (
                     op, remote_filename))

    def _dd(self, iff=None, off=None):
        cmd = ["dd", "status=none", "bs=%s" % BLOCKSIZE]
        if iff:
            cmd.append("if=%s" % iff)
        if off:
            cmd.append("of=%s" % off)
        return cmd

    def _execute_qvmrun(self, cmd, stdin, stdout, bufsize=MAX_LIST_SIZE):
        subcmd = " ".join(pipes.quote(s) for s in cmd)
        cmd = ["qvm-run", "--pass-io", "--", self.hostname, subcmd]
        return subprocess.Popen(
            cmd,
            stdin=stdin,
            stdout=stdout,
            close_fds=True
        )

    def _put(self, source_path, remote_filename):
        """Transfers a single file to the remote side."""
        self._validate_remote_filename("put", remote_filename)
        file_size = os.path.getsize(source_path.name)
        rempath = os.path.join(self.remote_dir, remote_filename)
        cmd = self._dd(off=rempath)
        progress.report_transfer(0, file_size)
        try:
            p = self._execute_qvmrun(cmd,
                                     stdin=subprocess.PIPE,
                                     stdout=open(os.devnull),
                                     bufsize=0)
        except Exception, e:
            raise BackendException(
                "Qubes VM put of %s (as %s) failed: (%s) %s" % (
                    source_path.name, remote_filename, type(e), e))
        buffer = bytearray(BLOCKSIZE)
        fobject = open(source_path.name, "rb")
        try:
            read_bytes = 0
            while True:
                b = fobject.readinto(buffer)
                if not b:
                    break
                read_bytes = read_bytes + b
                p.stdin.write(memoryview(buffer)[:b])
                progress.report_transfer(read_bytes, file_size)
        except Exception, e:
            p.kill()
            raise BackendException(
                "Qubes VM put of %s (as %s) failed: (%s) %s" % (
                    source_path.name, remote_filename, type(e), e))
        finally:
            p.stdin.close()
            fobject.close()
        progress.report_transfer(file_size, file_size)
        err = p.wait()
        if err != 0:
            raise BackendException(
                ("Qubes VM put of %s (as %s) failed: writing the "
                 "destination path exited with nonzero status %s") % (
                     source_path.name, remote_filename, err))

    def _get(self, remote_filename, local_path):
        """Retrieves a single file from the remote side."""
        self._validate_remote_filename("get", remote_filename)
        rempath = os.path.join(self.remote_dir, remote_filename)
        cmd = self._dd(iff=rempath)
        fobject = open(local_path.name, "wb")
        try:
            p = self._execute_qvmrun(cmd,
                                     stdin=open(os.devnull),
                                     stdout=fobject,
                                     bufsize=0)
        except Exception, e:
            raise BackendException(
                "Qubes VM get of %s (as %s) failed: (%s) %s" % (
                    remote_filename.name, local_path, type(e), e))
        finally:
            fobject.close()
        err = p.wait()
        if err != 0:
            raise BackendException(
                ("Qubes VM get of %s (as %s) failed: writing the "
                 "destination path exited with nonzero status %s") % (
                     remote_filename.name, local_path, err))

    def _list(self):
        """Lists the contents of the one duplicity dir on the remote side."""
        cmd = ["find", self.remote_dir, "-maxdepth", "1", "-print0"]
        try:
            p = self._execute_qvmrun(cmd,
                                     stdin=open(os.devnull, "rb"),
                                     stdout=subprocess.PIPE)
        except Exception, e:
            raise BackendException(
                "Qubes VM list of %s failed: %s" % (self.remote_dir, e))
        data = p.stdout.read(MAX_LIST_SIZE)
        p.stdout.close()
        err = p.wait()
        if err != 0:
            raise BackendException(
                ("Qubes VM list of %s failed: list command finished "
                "with nonzero status %s" % (self.remote_dir, err)))
        if not data:
            raise BackendException(
                ("Qubes VM list of %s failed: list command returned "
                "empty" % (self.remote_dir,)))
        filename_list = data.split("\0")
        if filename_list[0] != self.remote_dir:
            raise BackendException(
                ("Qubes VM list of %s failed: list command returned a "
                "filename_list for a path different from the remote folder") % (
                    self.remote_dir,))
        filename_list.pop(0)
        if filename_list[-1]:
            raise BackendException(
                ("Qubes VM list of %s failed: list command returned "
                "wrongly-terminated data or listing was too long") % (
                    self.remote_dir,))
        filename_list.pop()
        filename_list = [ p[len(self.remote_dir) + 1:] for p in filename_list ]
        if any(os.path.sep in p for p in filename_list):
            raise BackendException(
                ("Qubes VM list of %s failed: list command returned "
                "a path separator in the listing") % (
                    self.remote_dir,))
        return filename_list

    def _delete_list(self, filename_list):
        """Deletes all files in the list on the remote side."""
        if any(os.path.sep in p or "\0" in p for p in filename_list):
            raise BackendException(
                ("Qubes VM delete of files in %s failed: delete "
                 "command asked to delete a file with a path separator "
                 "or a null character in the listing") % (
                     self.remote_dir,))
        pathlist = [os.path.join(self.remote_dir, p) for p in filename_list]
        cmd = "set -e\n" + "\n".join("rm -f -- " + pipes.quote(p) for p in pathlist)
        try:
            p = self._execute_qvmrun(['bash'],
                                     stdin=subprocess.PIPE,
                                     stdout=open(os.devnull, "wb"))
            p.stdin.write(cmd)
            p.stdin.close()
        except Exception, e:
            raise BackendException(
                "Qubes VM delete of files in %s (%s) failed: %s" % (
                    self.remote_dir, cmd, e))
        err = p.wait()
        if err != 0:
            raise BackendException(
                ("Qubes VM delete of files in %s failed: delete "
                 "command finished with nonzero status %s") % (
                     self.remote_dir, err))

duplicity.backend.register_backend("qubesvm", QubesVMBackend)
duplicity.backend.uses_netloc.extend(['qubesvm'])
