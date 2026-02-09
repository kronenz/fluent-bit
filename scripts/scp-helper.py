#!/usr/bin/env python3
"""
SCP Helper using pexpect for password authentication.
Replaces sshpass for SCP file transfers.

Usage:
    SSH_HOST=host SSH_USER=user SSH_PASSWORD=pass scp-helper.py <source> <destination>

Environment variables:
    SSH_HOST: Remote host
    SSH_USER: SSH username
    SSH_PASSWORD: SSH password

Examples:
    scp-helper.py local_file user@host:/remote/path
    scp-helper.py /local/file /remote/path  (uses SSH_USER@SSH_HOST)
"""

import sys
import os
import pexpect

def main():
    # Get credentials from environment
    ssh_host = os.environ.get('SSH_HOST')
    ssh_user = os.environ.get('SSH_USER')
    ssh_password = os.environ.get('SSH_PASSWORD')

    if not all([ssh_host, ssh_user, ssh_password]):
        print("ERROR: SSH_HOST, SSH_USER, and SSH_PASSWORD environment variables must be set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) != 3:
        print("ERROR: Usage: scp-helper.py <source> <destination>", file=sys.stderr)
        sys.exit(1)

    source = sys.argv[1]
    destination = sys.argv[2]

    # If destination doesn't contain @, prepend user@host:
    if '@' not in destination:
        destination = f"{ssh_user}@{ssh_host}:{destination}"

    # Build SCP command
    scp_cmd = f"scp -o StrictHostKeyChecking=no {source} {destination}"

    try:
        # Spawn the SCP process
        child = pexpect.spawn(scp_cmd, encoding='utf-8', timeout=600)

        # Set up output streaming
        child.logfile_read = sys.stdout

        # Handle password prompt or host key confirmation
        index = child.expect([
            'password:',
            'Are you sure you want to continue connecting',
            pexpect.EOF,
            pexpect.TIMEOUT
        ])

        if index == 0:
            # Password prompt
            child.sendline(ssh_password)
            child.expect(pexpect.EOF)
        elif index == 1:
            # Host key confirmation
            child.sendline('yes')
            child.expect('password:')
            child.sendline(ssh_password)
            child.expect(pexpect.EOF)
        elif index == 2:
            # EOF - command completed without prompts (key-based auth?)
            pass
        else:
            # Timeout
            print("ERROR: SCP connection timeout", file=sys.stderr)
            child.close()
            sys.exit(1)

        # Close and get exit status
        child.close()
        exit_code = child.exitstatus if child.exitstatus is not None else 0
        sys.exit(exit_code)

    except pexpect.ExceptionPexpect as e:
        print(f"ERROR: SCP failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
