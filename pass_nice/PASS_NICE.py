import random
import re
import uuid
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import quote

import httpx

from .exceptions import (
    NetworkError,
    ParseError,
    SessionAlreadyInitializedError,
    SessionNotInitializedError,
    ValidationError,
)

from .types import Result, VerificationData


class PASS_NICE:
    """
    NICE아이디 본인인증 요청을 자동화해주는 비공식적인 모듈입니다. [요청업체: 한국도로교통공사]

    V2.1.0

    - 기능
        - SMS 본인인증 기능을 지원합니다.
        - MVNO 포함 모든 통신사를 지원합니다.
        - `httpx`를 기반으로 100% 비동기로 작동합니다.
    
    - Notes
        - checkplusData 형식은 NICE아이디를 사용하는 거의 모든 업체가 동일합니다.
        - 따라서, 다른 요청업체를 사용하시고 싶으시다면 checkplusDataRequest URL을 바꾸시면 동작합니다.
    """

    def __init__(self, cell_corp: Literal["SK", "KT", "LG", "SM", "KM", "LM"], proxy: Optional[str] = None):
        """
        Args:
            cell_corp: 인증 요청 대상자의 통신사 ('SK', 'KT', 'LG', 'SM', 'KM', 'LM')
            proxy: 프록시 URL (Ex: "http://host:port" 또는 "http://user:pass@host:port")
        
        """

        self.client = httpx.AsyncClient(proxy=proxy, timeout=30.0)
        self._cell_corp = cell_corp
        self._is_initialized, self._is_verify_sent = False, False

        self._HOST_ISP_MAPPING = {
            "SK": "COMMON_MOBILE_SKT",
            "SM": "COMMON_MOBILE_SKT", 
            "KT": "COMMON_MOBILE_KT",
            "KM": "COMMON_MOBILE_KT",
            "LG": "COMMON_MOBILE_LGU",
            "LM": "COMMON_MOBILE_LGU"
        }
        
        self._AUTH_TYPE: str = ""

    async def init_session(self, auth_type: Literal["sms", "app_push", "app_qr"], checkplus_custom_url: Optional[str] = None) -> Result: 
        """현재 클래스의 본인인증 세션을 초기화합니다.
        
        Args:
            auth_type: 인증 진행 방식 ('sms', 'app_push', 'app_qr')
            checkplus_custom_url: checkplus 데이터 요청 URL (기본값: 한국도로교통공사)

        Returns:
            Result[None]: 성공 시 반환되는 Result 객체

        Raises:
            SessionAlreadyInitializedError: 세션이 이미 초기화된 경우

        Examples:
            >>> await <Client>.init_session()
            Result(True, '세션 초기화에 성공했습니다.')
        """

        if self._is_initialized:
            raise SessionAlreadyInitializedError()

        if checkplus_custom_url is None:
            checkplus_custom_url = 'https://www.ex.co.kr:8070/recruit/company/nice/checkplus_success_company.jsp'

        try:
            checkplus_data_request = await self.client.get(checkplus_custom_url)
            checkplus_data = checkplus_data_request.text
            
        except httpx.RequestError as e:
            raise NetworkError(f"요청업체와의 통신에 실패했습니다: {str(e)}", 1)

        m = self._parse_html(checkplus_data, "m", "input")
        encode_data = self._parse_html(checkplus_data, "EncodeData", "input")

        wc_cookie = f'{uuid.uuid4()}_T_{random.randint(10000, 99999)}_WC'  
        self.client.cookies.update({'wcCookie': wc_cookie})

        try:
            checkplus_request = await self.client.post(
                'https://nice.checkplus.co.kr/CheckPlusSafeModel/checkplus.cb',
                data={
                    'm': m, 
                    'EncodeData': encode_data
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 3)

        self._SERVICE_INFO = self._parse_html(checkplus_request.text, "SERVICE_INFO")

        try:
            await self.client.post(
                'https://nice.checkplus.co.kr/cert/main/menu',
                data={
                    'accTkInfo': self._SERVICE_INFO
                }
            )

            cert_method_request = await self.client.post(
                'https://nice.checkplus.co.kr/cert/mobileCert/method', 
                data={
                    "accTkInfo": self._SERVICE_INFO,
                    "selectMobileCo": self._cell_corp, 
                    "os": "Windows"
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 7)

        self._CERT_INFO_HASH = self._parse_html(cert_method_request.text, "certInfoHash", "input")

        
        auth_type_action = auth_type
        if auth_type in ["app_push", "app_qr"]:
            auth_type_action = auth_type.split("app_")[1]
        
        try:
            cert_proc_request = await self.client.post(
                url=f'https://nice.checkplus.co.kr/cert/mobileCert/{auth_type_action}/certification',
                data = {
                    "certInfoHash": self._CERT_INFO_HASH,
                    "accTkInfo": self._SERVICE_INFO,
                    "mobileCertAgree": "Y"
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 9)

        if auth_type in ["sms", "app_push"]:
            self._CAPTCHA_VERSION = self._parse_html(cert_proc_request.text, "captchaVersion")

        else:
            self._CAPTCHA_VERSION = ""

        self._AUTH_TYPE = auth_type
        self._is_initialized = True

        return Result(True, '세션 초기화에 성공했습니다.')

    async def retrieve_captcha(self) -> Result[bytes]:
        """
        현재 클래스의 초기화된 세션을 기준으로 본인인증 요청 전송시에 필요한 캡챠 이미지를 반환합니다.

        Returns:
            Result[bytes]: 성공 시 캡챠 이미지 바이트 데이터를 포함한 Result 객체
            
        Raises:
            SessionNotInitializedError: 세션이 초기화되지 않은 경우

        Examples:
            >>> await <Client>.retrieve_captcha()
            <Result[bytes]>
        """ 

        if not self._is_initialized or not hasattr(self, '_CAPTCHA_VERSION'):
            raise SessionNotInitializedError("캡챠 이미지를 확인하기 위해서는 세션 초기화가 필요합니다.")

        try:
            captcha_request = await self.client.get(f'https://nice.checkplus.co.kr/cert/captcha/image/{self._CAPTCHA_VERSION}')
            content = captcha_request.content
            
        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        return Result(True, "캡챠 이미지 확인에 성공했습니다.", content)

    # ----- 인증 전송 및 생성 ----- #
    async def send_sms_verification(
        self, name: str, birthdate: str, 
        gender: Literal[
            "1", "2", "3", "4",  # 내국인
            "5", "6", "7", "8",  # 외국인
        ], 
        phone_number: str, captcha_answer: str
    ) -> Result[None]:
        """
        SMS로 본인인증 요청을 전송합니다.

        Args:
            name: 이름 (Ex: 홍길동)
            birthdate: 생년월일 (YYMMDD)
            gender: 성별코드 (주민등록번호상 7자리에 위치한 성별코드)
            phone_number: 휴대전화번호 (11자리 숫자로만 이루어진 문자열 혹은 13자리 하이픈 포함 문자열)
            captcha_answer: 캡챠 코드 (6자리 숫자)
        
        Returns:
            Result[None]: SMS 전송 성공/실패 결과
            
        Raises:
            SessionNotInitializedError: 세션이 정상적으로 초기화되지 않았거나, SMS 방식으로 초기화되지 않았을 시 발생하는 예외입니다.
            ValidationError: 생년월일, 휴대전화번호, 캡챠 코드 셋 중 1개 이상이 조건에 맞지 않을 시 발생하는 예외입니다.

        Examples:
        >>> await <Client>.send_sms_verification("홍길동", "0001013", "01012345678", "123456")
        Result(status=True, message='휴대폰 본인인증 요청을 성공적으로 전송했습니다.', data=None)
        """
        # 세션이 정상적으로 초기화되었는지 확인
        if not self._is_initialized: 
            raise SessionNotInitializedError("SMS 본인인증 요청을 보내기 위해서는 세션 초기화가 필요합니다.")

        if not self._AUTH_TYPE == "sms":
            raise SessionNotInitializedError("SMS 본인인증 요청을 보내기 위해서는 SMS 방식으로 세션을 초기화해주셔야 합니다.")

        birthdate, phone_number, captcha_answer = self._verify_input(birthdate, phone_number, captcha_answer)

        # SMS 전송 요청
        try:
            sms_proc_request = await self.client.post(
                'https://nice.checkplus.co.kr/cert/mobileCert/sms/certification/proc', 
                headers={
                    "x-service-info": self._SERVICE_INFO
                },
                data={
                    "userNameEncoding": quote(name),
                    "userName": name,
                    "myNum1": birthdate,
                    "myNum2": gender,
                    "mobileNo": phone_number,
                    "captchaAnswer": captcha_answer
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        # SMS 전송 성공 여부 확인 (API 오류 반환시 Result로 반환)
        response_json = sms_proc_request.json()
        if response_json.get('code') != "SUCCESS":
            error_msg = response_json.get('message', '올바른 본인인증 정보를 입력해주세요.')
            return Result(False, error_msg)

        self._verification_data = VerificationData(
            name=name,
            birthdate=datetime.strptime(birthdate, "%y%m%d"),
            gender="1" if gender in ["1", "3", "5", "7"] else "2",
            phone_number=phone_number,
            mobile_carrier=self._cell_corp
        )

        self._is_verify_sent = True

        return Result(True, "휴대폰 본인인증 요청을 성공적으로 전송했습니다.")
    
    async def send_push_verification(
        self, name: str,
        phone_number: str, captcha_answer: str
    ) -> Result[None]:
        """
        PASS 앱으로 본인인증 요청을 전송합니다.

        Args:
            name: 이름 (Ex: 홍길동)
            phone_number: 휴대전화번호 (11자리 숫자로만 이루어진 문자열 혹은 13자리 하이픈 포함 문자열)
            captcha_answer: 캡챠 코드 (6자리 숫자)
        
        Returns:
            Result[None]: 인증 전송 성공/실패 결과
            
        Raises:
            SessionNotInitializedError: 세션이 정상적으로 초기화되지 않았거나, SMS 방식으로 초기화되지 않았을 시 발생하는 예외입니다.
            ValidationError: 생년월일, 휴대전화번호, 캡챠 코드 셋 중 1개 이상이 조건에 맞지 않을 시 발생하는 예외입니다.

        Examples:
        >>> await <Client>.send_push_verification("홍길동", "01012345678", "123456")
        Result(status=True, message='PASS 본인인증 요청을 성공적으로 전송했습니다.', data=None)
        """
        # 세션이 정상적으로 초기화되었는지 확인
        if not self._is_initialized: 
            raise SessionNotInitializedError("PASS 본인인증 요청을 보내기 위해서는 세션 초기화가 필요합니다.")

        if not self._AUTH_TYPE == "app_push":
            raise SessionNotInitializedError("PASS 본인인증 요청을 보내기 위해서는 app_push 방식으로 세션을 초기화해주셔야 합니다.")

        _, phone_number, captcha_answer = self._verify_input("000000", phone_number, captcha_answer)

        # PASS 앱 인증 전송 요청
        try:
            sms_proc_request = await self.client.post(
                'https://nice.checkplus.co.kr/cert/mobileCert/push/certification/proc', 
                headers={
                    "x-service-info": self._SERVICE_INFO
                },
                data={
                    "userNameEncoding": quote(name),
                    "userName": name,
                    "mobileNo": phone_number,
                    "captchaAnswer": captcha_answer
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        # SMS 전송 성공 여부 확인 (API 오류 반환시 Result로 반환)
        response_json = sms_proc_request.json()
        if not response_json.get('code') == "SUCCESS":
            error_msg = response_json.get('message', '올바른 본인인증 정보를 입력해주세요.')
            return Result(False, error_msg)

        self._is_verify_sent = True

        return Result(True, "PASS 본인인증 요청을 성공적으로 전송했습니다.")

    async def create_qr_verification(self) -> Result[bytes]:
        """
        PASS 앱 QR 본인인증을 세션을 생성합니다.
        해당 함수는 개인정보를 입력받지 않습니다. (VerificationData 반환값은 같습니다.)
        
        Returns:
            Result[bytes]: 인증 전송 성공/실패 결과
            
        Raises:
            SessionNotInitializedError: 세션이 정상적으로 초기화되지 않았거나, QR 방식으로 초기화되지 않았을 시 발생하는 예외입니다.
            ParseError: NICE 응답값에서 QR 코드 정보를 파싱하지 못했을 시 발생하는 예외입니다.

        Examples:
        >>> await <Client>.create_qr_verification()
        Result(status=True, message='QR코드 번호 (6자리 숫자)', data=qrcode_img)
        """
        try:
            qrcode_request = await self.client.post(
                "https://nice.checkplus.co.kr/cert/mobileCert/qr/certification",
                headers={
                    "x-service-info": self._SERVICE_INFO
                },
                data={
                    "certInfoHash": self._CERT_INFO_HASH,
                    "accTkInfo": self._SERVICE_INFO,
                    "mobileCertAgree": "Y"
                }
            )
        
        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        match = re.search(r'<div class="qr_num">(\d+)</div>', qrcode_request.text)
        if match:
            qr_number = match.group(1)

        else:
            raise ParseError("QR코드 번호 데이터 파싱에 실패했습니다.")

        try:
            qrcode_request = await self.client.get(f"https://nice.checkplus.co.kr/cert/qr/image/{qr_number}")
            qr_content = qrcode_request.content

        except Exception as e:
            raise NetworkError(f"QR코드 이미지 확인 중 문제가 발생했습니다: {str(e)}")
        
        self._is_verify_sent = True

        return Result(status=True, message=qr_number, data=qr_content)

    # ----- 인증 확인 및 결과값 반환 ----- #
    async def check_sms_verification(self, sms_code: str) -> Result[VerificationData]:
        """
        전송된 SMS 코드를 확인합니다.

        Args:
            sms_code: 휴대전화로 전송된 SMS 코드 (6자리)
        
        Returns:
            Result[VerificationData]: 성공 시 본인인증 데이터를 포함한 Result 객체를 반환합니다.
            
        Raises:
            SessionNotInitializedError: 세션이 올바르게 초기화되지 않은 경우 발생하는 예외입니다.
            ValidationError: SMS 코드 형식이 올바르지 않은 경우 발생하는 예외입니다.
        
        Examples:
            >>> <Client>.check_sms_verification(sms_code="123456")
            Result(success=True, data=<VerificationData>)
        """
        if not self._is_initialized or not hasattr(self, '_CAPTCHA_VERSION'):
            raise SessionNotInitializedError()

        if not self._is_verify_sent:
            return Result(False, "아직 인증을 진행하지 않았습니다.")

        if not self._AUTH_TYPE == "sms":
            return Result(False, "현재 세션은 SMS 인증 방식이 아닙니다.")

        # SMS 코드 검증
        if not sms_code.strip() or len(sms_code) != 6 or not sms_code.isdigit():
            raise ValidationError("SMS 코드는 6자리 숫자여야 합니다.")

        try:
            sms_confirm_request = await self.client.post(
                url='https://nice.checkplus.co.kr/cert/mobileCert/sms/confirm/proc',
                headers={
                    "X-Requested-With": "XMLHTTPRequest",
                    "x-service-info": self._SERVICE_INFO
                },
                data={
                    "certCode": sms_code
                }
            )
            
        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 2)

        try:
            response_json = sms_confirm_request.json()
            response_code = response_json.get('code')
        
        except (KeyError, ValueError) as e:
            raise ParseError(f"나이스 응답 데이터 파싱에 실패했습니다: {str(e)}", 3)

        if response_code == "RETRY":
            return Result(False, "올바른 인증코드를 입력해주세요.")

        if not response_code == "SUCCESS":
            error_msg = response_json.get('message', '인증 확인 도중 문제가 발생하였습니다.')
            return Result(False, error_msg)

        return Result(True, "본인인증이 완료되었습니다.", self._verification_data)

    async def check_push_verification(self) -> Result[VerificationData]:
        """
        PASS 앱 본인인증 완료 여부를 확인합니다.

        Returns:
            Result[VerificationData]: 성공 시 본인인증 데이터를 포함한 Result 객체를 반환합니다.

        Raises:
            SessionNotInitializedError: 세션이 올바르게 초기화되지 않은 경우 발생하는 예외입니다.

        Examples:
            >>> await client.check_push_verification()
            Result(status=True, message='본인인증이 완료되었습니다.', data=<VerificationData>)
        """
        if not self._is_initialized or not hasattr(self, '_CAPTCHA_VERSION'):
            raise SessionNotInitializedError()

        if not self._is_verify_sent:
            return Result(False, "아직 인증을 진행하지 않았습니다.")
    
        if self._AUTH_TYPE not in ["app_push", "app_qr"]:
            return Result(False, "현재 세션은 PASS 앱 인증 방식이 아닙니다.")

        try:
            check_request = await self.client.post(
                "https://nice.checkplus.co.kr/cert/polling/confirm/check/proc",
                headers={
                    "x-service-info": self._SERVICE_INFO
                }
            )
        
        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)
    
        response_json = check_request.json()
    
        if not str(response_json.get('code', '0001')) == "0000":
            return Result(False, "아직 유저가 인증을 진행하지 않았습니다.")
        
        verification_data = await self._get_verification_data()
        
        return Result(True, "본인인증이 완료되었습니다.", verification_data)

    async def check_qr_verification(self) -> Result[VerificationData]:
        """
        PASS 앱 QR 본인인증 완료 여부를 확인합니다.
        해당 인증 방식은 PASS 앱 알림 본인인증과 확인 로직이 동일합니다.
        따라서, 함수 내부에서 check_push_verification 함수를 호출하고 결과를 그대로 반환합니다.

        Returns:
            Result[VerificationData]: 성공 시 본인인증 데이터를 포함한 Result 객체를 반환합니다.

        Raises:
            SessionNotInitializedError: 세션이 올바르게 초기화되지 않은 경우 발생하는 예외입니다.

        Examples:
            >>> await client.check_qr_verification()
            Result(status=True, message='본인인증이 완료되었습니다.', data=<VerificationData>)
        """
        result = await self.check_push_verification()
        return result

    async def _get_verification_data(self) -> VerificationData:
        auth_type_action = self._AUTH_TYPE
        if self._AUTH_TYPE in ["app_push", "app_qr"]:
            auth_type_action = self._AUTH_TYPE.split("app_")[1]
        
        try:
            await self.client.post(
                f"https://nice.checkplus.co.kr/cert/mobileCert/{auth_type_action}/confirm/proc",
                headers={
                    "x-service-info": self._SERVICE_INFO
                }
            )

            cert_result_request = await self.client.post(
                "https://nice.checkplus.co.kr/cert/result/send",
                data={
                    "accTkInfo": self._SERVICE_INFO
                }
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        query_string = self._parse_html(cert_result_request.text, "queryString")

        try:
            decrypt_data_request = await self.client.get(
                f"https://www.ex.co.kr:8070/recruit/company/nice/checkplus_success_company.jsp?{query_string}"
            )

        except httpx.RequestError as e:
            raise NetworkError(f"나이스 서버와 통신에 실패했습니다: {str(e)}", 1)

        decrypt_response_html = decrypt_data_request.text

        name = self._parse_form_value(decrypt_response_html, "NICE_NAME")
        gender = self._parse_form_value(decrypt_response_html, "NICE_GENDER")
        birthdate_str = self._parse_form_value(decrypt_response_html, "NICE_BIRTHEDATE")  # YYYYMMDD 형식
        phone_number = self._parse_form_value(decrypt_response_html, "NICE_MOBILENO")

        return VerificationData(
            name=name,
            birthdate=datetime.strptime(birthdate_str, "%Y%m%d"),
            gender=gender,  # type: ignore
            phone_number=phone_number,
            mobile_carrier=self._cell_corp
        )

    # ----- helper ----- #
    @staticmethod
    def _parse_html(html: str, var_name: str, parse_type: Literal["const", "input"] = "const") -> str:
        if parse_type == "const":
            pattern = rf'const\s+{var_name}\s*=\s*"([^"]+)"'
        
        else:
            pattern = rf'<input\s+type=["\']hidden["\']\s+name=["\']{var_name}["\']\s+value=["\']([^"\'\']+)["\']>'

        match = re.search(pattern, html)
        if not match:
            raise ParseError(f"{var_name} 데이터 파싱에 실패했습니다.")
        
        return match.group(1)

    @staticmethod
    def _verify_input(birthdate: str, phone_number: str, captcha_answer: str) -> tuple[str, str, str]:
        """입력값을 검증하고 NICE 형식에 맞게 수정하는 함수입니다."""
        # 생년월일 검증
        if not len(birthdate) == 6: # 생년월일이 6자리가 아니라면
            if len(birthdate) == 8: # 생년월일이 8자리라면 (NICE 형식에 맞추기 위해 6자리로 변환)
                birthdate = birthdate[2:8]
            
            else: # 생년월일이 6, 8자리 모두 아닐 경우 ValidationError 예외 처리
                raise ValidationError("올바르지 않은 생년월일을 입력하셨습니다.")

        # 휴대전화번호 검증
        phone_number = phone_number.replace("-", "") # 하이픈 삭제
        if not len(phone_number) == 11:
            raise ValidationError("올바르지 않은 휴대전화번호를 입력하셨습니다.")

        # 캡챠 코드 검증
        if not captcha_answer.isdigit(): # 숫자로 이루어지지 않은 경우
            raise ValidationError("올바르지 않은 캡챠 코드를 입력하셨습니다.")
        
        if not len(captcha_answer) == 6: # 6자리가 아닌 경우
            raise ValidationError("올바르지 않은 캡챠 코드를 입력하셨습니다.")

        return (birthdate, phone_number, captcha_answer)

    @staticmethod
    def _parse_form_value(html: str, field_name: str) -> str:
        """NICE 템플릿 형식의 HTML Form 값을 파싱합니다."""
        pattern = rf"form1\.{field_name}\.value\s*=\s*'([^']*)'"
        match = re.search(pattern, html)
        
        if not match:
            raise ParseError(f"{field_name} 데이터 파싱에 실패했습니다.")
        
        return match.group(1)

    # ----- context manager ----- #
    async def close(self) -> None:
        """HTTP 클라이언트를 종료합니다."""
        await self.client.aclose()

    async def __aenter__(self):
        """async with 구문 지원"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """async with 구문 지원"""
        await self.close()
