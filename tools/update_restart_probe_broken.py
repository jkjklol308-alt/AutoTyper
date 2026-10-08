"""A build that never signals its start-up.

The rollback half of the end-to-end update probe needs a *new* build that is a
real executable but never comes up (the failure mode a message box, a missing
DLL or a crash produces in the field). This one exits before writing the
start-up marker, so the swap script has to notice, put the previous build back
and start it again.
"""

import sys

print("this build never signals its window", flush=True)
sys.exit(3)
