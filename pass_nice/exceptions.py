"""
PASS-NICE 커스텀 예외 클래스들
"""


class PassNiceError(Exception):
    """PASS-NICE 모듈의 기본 예외 클래스"""
    def __init__(self, message: str, error_code: int = 0):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class SessionNotInitializedError(PassNiceError):
    """세션이 초기화되지 않았을 때 발생하는 예외"""
    def __init__(self, message: str = "세션이 초기화되지 않았습니다."):
        super().__init__(message, 0)


class SessionAlreadyInitializedError(PassNiceError):
    """세션이 이미 초기화되었을 때 발생하는 예외"""
    def __init__(self, message: str = "이미 초기화된 세션입니다."):
        super().__init__(message, 0)


class NetworkError(PassNiceError):
    """네트워크 오류 시 발생하는 예외"""
    def __init__(self, message: str, error_code: int = 1):
        super().__init__(message, error_code)


class ParseError(PassNiceError):
    """데이터 파싱 오류 시 발생하는 예외"""
    def __init__(self, message: str, error_code: int = 2):
        super().__init__(message, error_code)


class ValidationError(PassNiceError):
    """입력 데이터 검증 오류 시 발생하는 예외"""
    def __init__(self, message: str, error_code: int = 3):
        super().__init__(message, error_code)
