Qubes OS backend for Duplicity backups
======================================

This file is an extension to [Duplicity](http://duplicity.nongnu.org/)
0.7.x that allows it to back up any files in a Qubes OS
dom0 (such as VM images) directly to a Duplicity backup
directory within a running VM of the Qubes OS system.

Instructions:

1. Install Duplicity on dom0.
   The usual `sudo qubes-dom0-update duplicity` works well.
2. Place the file `qubesvmbackend.py` in this repository
   within the directory
   `/usr/lib64/python2.7/site-packages/duplicity/backends`.
3. You are ready to back up your system to a VM!

Usage example
-------------

Duplicity can be used as the following example shows:

```
duplicity /var/lib/qubes qubesvm://backupvm/mnt/externaldisk
```

In this example, Duplicity will back up the directory
`/var/lib/qubes` into the VM `backupvm`, taking care to place
the output of the backup into `/mnt/externaldisk`
(which is, presumably, an external disk that you mounted
within said VM).

Noteworthy: subsequent invocations of the same command
will perform incremental backups, such that only the
changes between the last backup will be stored, leading to
huge disk space savings.  Note that incremental backups
don't go that much faster than full backups, since Duplicity
still needs to read all the source files entirely, before
deciding which parts have changed since the last backup.
However, disk I/O on the receiving side (the VM) is almost
nil for the duration of the incremental backup (except when
writing newly-discovered changes to it).

Of course, you can use any Duplicity features, such as
PGP encryption and compression.
