"""
PASS-NICE: NICE 아이디 본인인증 자동화 모듈

NICE 아이디 SMS 본인인증 기능을 지원하며, MVNO를 포함한 모든 통신사를 지원합니다.

사용 예시:
    import pass_nice
    
    client = pass_nice.PASS_NICE("SK")
    await client.init_session()
"""

__version__ = "2.1.1"
__author__ = "Sunrise"
__email__ = "sunr1s2@proton.me"

from .PASS_NICE import PASS_NICE
from .types import Result

from .exceptions import *  # noqa: F401,F403

__all__ = [
    "PASS_NICE",
    "Result",
    "__version__"
]