"""Deprecated v2 import alias. New code uses vc_common."""
import sys
import vc_common as _common

sys.modules[__name__] = _common
